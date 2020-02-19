// Copyright (C) The Arvados Authors. All rights reserved.
//
// SPDX-License-Identifier: AGPL-3.0

package controller

import (
	"bytes"
	"context"
	"net"
	"net/url"
	"os"
	"path/filepath"

	"git.arvados.org/arvados.git/lib/boot"
	"git.arvados.org/arvados.git/lib/config"
	"git.arvados.org/arvados.git/lib/controller/rpc"
	"git.arvados.org/arvados.git/sdk/go/arvados"
	"git.arvados.org/arvados.git/sdk/go/arvadosclient"
	"git.arvados.org/arvados.git/sdk/go/auth"
	"git.arvados.org/arvados.git/sdk/go/ctxlog"
	"git.arvados.org/arvados.git/sdk/go/keepclient"
	check "gopkg.in/check.v1"
)

var _ = check.Suite(&IntegrationSuite{})

type testCluster struct {
	booter        boot.Booter
	config        arvados.Config
	controllerURL *url.URL
}

type IntegrationSuite struct {
	testClusters map[string]*testCluster
}

func (s *IntegrationSuite) SetUpSuite(c *check.C) {
	if forceLegacyAPI14 {
		c.Skip("heavy integration tests don't run with forceLegacyAPI14")
		return
	}

	cwd, _ := os.Getwd()
	s.testClusters = map[string]*testCluster{
		"z1111": nil,
		"z2222": nil,
		"z3333": nil,
	}
	port := map[string]string{}
	for id := range s.testClusters {
		port[id] = func() string {
			ln, err := net.Listen("tcp", "localhost:0")
			c.Assert(err, check.IsNil)
			ln.Close()
			_, port, err := net.SplitHostPort(ln.Addr().String())
			c.Assert(err, check.IsNil)
			return port
		}()
	}
	for id := range s.testClusters {
		yaml := `Clusters:
  ` + id + `:
    Services:
      Controller:
        ExternalURL: https://localhost:` + port[id] + `
    TLS:
      Insecure: true
    Login:
      LoginCluster: z1111
    RemoteClusters:
      z1111:
        Host: localhost:` + port["z1111"] + `
        Scheme: https
        Insecure: true
      z2222:
        Host: localhost:` + port["z2222"] + `
        Scheme: https
        Insecure: true
      z3333:
        Host: localhost:` + port["z3333"] + `
        Scheme: https
        Insecure: true
`
		loader := config.NewLoader(bytes.NewBufferString(yaml), ctxlog.TestLogger(c))
		loader.Path = "-"
		loader.SkipLegacy = true
		loader.SkipAPICalls = true
		cfg, err := loader.Load()
		c.Assert(err, check.IsNil)
		s.testClusters[id] = &testCluster{
			booter: boot.Booter{
				SourcePath:           filepath.Join(cwd, "..", ".."),
				LibPath:              filepath.Join(cwd, "..", "..", "tmp"),
				ClusterType:          "test",
				ListenHost:           "localhost",
				ControllerAddr:       ":0",
				OwnTemporaryDatabase: true,
				Stderr:               ctxlog.LogWriter(c.Log),
			},
			config: *cfg,
		}
		s.testClusters[id].booter.Start(context.Background(), &s.testClusters[id].config)
	}
	for _, tc := range s.testClusters {
		au, ok := tc.booter.WaitReady()
		c.Assert(ok, check.Equals, true)
		u := url.URL(*au)
		tc.controllerURL = &u
	}
}

func (s *IntegrationSuite) TearDownSuite(c *check.C) {
	for _, c := range s.testClusters {
		c.booter.Stop()
	}
}

func (s *IntegrationSuite) conn(clusterID string) (*rpc.Conn, context.Context, *arvados.Client, *keepclient.KeepClient) {
	cl := s.testClusters[clusterID].config.Clusters[clusterID]
	conn := rpc.NewConn(clusterID, s.testClusters[clusterID].controllerURL, true, rpc.PassthroughTokenProvider)
	rootctx := auth.NewContext(context.Background(), auth.NewCredentials(cl.SystemRootToken))
	ac, err := arvados.NewClientFromConfig(&cl)
	if err != nil {
		panic(err)
	}
	ac.AuthToken = cl.SystemRootToken
	arv, err := arvadosclient.New(ac)
	if err != nil {
		panic(err)
	}
	kc := keepclient.New(arv)
	return conn, rootctx, ac, kc
}

func (s *IntegrationSuite) TestLoopDetection(c *check.C) {
	conn1, rootctx1, _, _ := s.conn("z1111")
	conn3, rootctx3, ac3, kc3 := s.conn("z3333")

	_, err := conn1.CollectionGet(rootctx1, arvados.GetOptions{UUID: "1f4b0bc7583c2a7f9102c395f4ffc5e3+45"})
	c.Check(err, check.ErrorMatches, `.*404 Not Found.*`)

	var coll3 arvados.Collection
	fs3, err := coll3.FileSystem(ac3, kc3)
	if err != nil {
		c.Error(err)
	}
	f, err := fs3.OpenFile("foo", os.O_CREATE|os.O_RDWR, 0777)
	f.Write([]byte("foo"))
	f.Close()
	mtxt, err := fs3.MarshalManifest(".")
	coll3, err = conn3.CollectionCreate(rootctx3, arvados.CreateOptions{Attrs: map[string]interface{}{
		"manifest_text": mtxt,
	}})
	coll, err := conn1.CollectionGet(rootctx1, arvados.GetOptions{UUID: "1f4b0bc7583c2a7f9102c395f4ffc5e3+45"})
	c.Check(err, check.IsNil)
	c.Check(coll.PortableDataHash, check.Equals, "1f4b0bc7583c2a7f9102c395f4ffc5e3+45")
}
