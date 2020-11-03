// Copyright (C) The Arvados Authors. All rights reserved.
//
// SPDX-License-Identifier: AGPL-3.0

package costanalyzer

import (
	"bytes"
	"io"
	"io/ioutil"
	"os"
	"regexp"
	"testing"

	"git.arvados.org/arvados.git/sdk/go/arvados"
	"git.arvados.org/arvados.git/sdk/go/arvadosclient"
	"git.arvados.org/arvados.git/sdk/go/arvadostest"
	"git.arvados.org/arvados.git/sdk/go/keepclient"
	"gopkg.in/check.v1"
)

func Test(t *testing.T) {
	check.TestingT(t)
}

var _ = check.Suite(&Suite{})

type Suite struct{}

func (s *Suite) TearDownSuite(c *check.C) {
	// Undo any changes/additions to the database so they don't affect subsequent tests.
	arvadostest.ResetEnv()
}

func (s *Suite) SetUpSuite(c *check.C) {
	arvadostest.StartAPI()
	arvadostest.StartKeep(2, true)

	// Get the various arvados, arvadosclient, and keep client objects
	ac := arvados.NewClientFromEnv()
	arv, err := arvadosclient.MakeArvadosClient()
	c.Assert(err, check.Equals, nil)
	arv.ApiToken = arvadostest.ActiveToken
	kc, err := keepclient.MakeKeepClient(arv)
	c.Assert(err, check.Equals, nil)

	standardE4sV3JSON := `{
    "Name": "Standard_E4s_v3",
    "ProviderType": "Standard_E4s_v3",
    "VCPUs": 4,
    "RAM": 34359738368,
    "Scratch": 64000000000,
    "IncludedScratch": 64000000000,
    "AddedScratch": 0,
    "Price": 0.292,
    "Preemptible": false
}`
	standardD32sV3JSON := `{
    "Name": "Standard_D32s_v3",
    "ProviderType": "Standard_D32s_v3",
    "VCPUs": 32,
    "RAM": 137438953472,
    "Scratch": 256000000000,
    "IncludedScratch": 256000000000,
    "AddedScratch": 0,
    "Price": 1.76,
    "Preemptible": false
}`

	standardA1V2JSON := `{
    "Name": "a1v2",
    "ProviderType": "Standard_A1_v2",
    "VCPUs": 1,
    "RAM": 2147483648,
    "Scratch": 10000000000,
    "IncludedScratch": 10000000000,
    "AddedScratch": 0,
    "Price": 0.043,
    "Preemptible": false
}`

	standardA2V2JSON := `{
    "Name": "a2v2",
    "ProviderType": "Standard_A2_v2",
    "VCPUs": 2,
    "RAM": 4294967296,
    "Scratch": 20000000000,
    "IncludedScratch": 20000000000,
    "AddedScratch": 0,
    "Price": 0.091,
    "Preemptible": false
}`

	// Our fixtures do not actually contain file contents. Populate the log collections we're going to use with the node.json file
	createNodeJSON(c, arv, ac, kc, arvadostest.CompletedContainerRequestUUID, arvadostest.LogCollectionUUID, standardE4sV3JSON)
	createNodeJSON(c, arv, ac, kc, arvadostest.CompletedContainerRequestUUID2, arvadostest.LogCollectionUUID2, standardD32sV3JSON)

	createNodeJSON(c, arv, ac, kc, arvadostest.CompletedDiagnosticsContainerRequest1UUID, arvadostest.DiagnosticsContainerRequest1LogCollectionUUID, standardA1V2JSON)
	createNodeJSON(c, arv, ac, kc, arvadostest.CompletedDiagnosticsContainerRequest2UUID, arvadostest.DiagnosticsContainerRequest2LogCollectionUUID, standardA1V2JSON)
	createNodeJSON(c, arv, ac, kc, arvadostest.CompletedDiagnosticsHasher1ContainerRequestUUID, arvadostest.Hasher1LogCollectionUUID, standardA1V2JSON)
	createNodeJSON(c, arv, ac, kc, arvadostest.CompletedDiagnosticsHasher2ContainerRequestUUID, arvadostest.Hasher2LogCollectionUUID, standardA2V2JSON)
	createNodeJSON(c, arv, ac, kc, arvadostest.CompletedDiagnosticsHasher3ContainerRequestUUID, arvadostest.Hasher3LogCollectionUUID, standardA1V2JSON)
}

func createNodeJSON(c *check.C, arv *arvadosclient.ArvadosClient, ac *arvados.Client, kc *keepclient.KeepClient, crUUID string, logUUID string, nodeJSON string) {
	// Get the CR
	var cr arvados.ContainerRequest
	err := arv.Get("container_requests", crUUID, arvadosclient.Dict{}, &cr)
	c.Assert(err, check.Equals, nil)
	c.Assert(cr.LogUUID, check.Equals, logUUID)

	// Get the log collection
	var coll arvados.Collection
	err = arv.Get("collections", cr.LogUUID, arvadosclient.Dict{}, &coll)
	c.Assert(err, check.IsNil)

	// Create a node.json file -- the fixture doesn't actually contain the contents of the collection.
	fs, err := coll.FileSystem(ac, kc)
	c.Assert(err, check.IsNil)
	f, err := fs.OpenFile("node.json", os.O_CREATE|os.O_RDWR|os.O_TRUNC, 0777)
	c.Assert(err, check.IsNil)
	_, err = io.WriteString(f, nodeJSON)
	c.Assert(err, check.IsNil)
	err = f.Close()
	c.Assert(err, check.IsNil)

	// Flush the data to Keep
	mtxt, err := fs.MarshalManifest(".")
	c.Assert(err, check.IsNil)
	c.Assert(mtxt, check.NotNil)

	// Update collection record
	err = arv.Update("collections", cr.LogUUID, arvadosclient.Dict{"collection": arvadosclient.Dict{"manifest_text": mtxt}}, &coll)
	c.Assert(err, check.IsNil)
}

func (*Suite) TestUsage(c *check.C) {
	var stdout, stderr bytes.Buffer
	exitcode := Command.RunCommand("costanalyzer.test", []string{"-help", "-log-level=debug"}, &bytes.Buffer{}, &stdout, &stderr)
	c.Check(exitcode, check.Equals, 1)
	c.Check(stdout.String(), check.Equals, "")
	c.Check(stderr.String(), check.Matches, `(?ms).*Usage:.*`)
}

func (*Suite) TestContainerRequestUUID(c *check.C) {
	var stdout, stderr bytes.Buffer
	// Run costanalyzer with 1 container request uuid
	exitcode := Command.RunCommand("costanalyzer.test", []string{"-uuid", arvadostest.CompletedContainerRequestUUID}, &bytes.Buffer{}, &stdout, &stderr)
	c.Check(exitcode, check.Equals, 0)
	c.Check(stderr.String(), check.Matches, "(?ms).*supplied uuids in .*")

	uuidReport, err := ioutil.ReadFile("results/" + arvadostest.CompletedContainerRequestUUID + ".csv")
	c.Assert(err, check.IsNil)
	c.Check(string(uuidReport), check.Matches, "(?ms).*TOTAL,,,,,,,,,7.01302889")
	re := regexp.MustCompile(`(?ms).*supplied uuids in (.*?)\n`)
	matches := re.FindStringSubmatch(stderr.String()) // matches[1] contains a string like 'results/2020-11-02-18-57-45-aggregate-costaccounting.csv'

	aggregateCostReport, err := ioutil.ReadFile(matches[1])
	c.Assert(err, check.IsNil)

	c.Check(string(aggregateCostReport), check.Matches, "(?ms).*TOTAL,7.01302889")
}

func (*Suite) TestDoubleContainerRequestUUID(c *check.C) {
	var stdout, stderr bytes.Buffer
	// Run costanalyzer with 2 container request uuids
	exitcode := Command.RunCommand("costanalyzer.test", []string{"-uuid", arvadostest.CompletedContainerRequestUUID, "-uuid", arvadostest.CompletedContainerRequestUUID2}, &bytes.Buffer{}, &stdout, &stderr)
	c.Check(exitcode, check.Equals, 0)
	c.Check(stderr.String(), check.Matches, "(?ms).*supplied uuids in .*")

	uuidReport, err := ioutil.ReadFile("results/" + arvadostest.CompletedContainerRequestUUID + ".csv")
	c.Assert(err, check.IsNil)
	c.Check(string(uuidReport), check.Matches, "(?ms).*TOTAL,,,,,,,,,7.01302889")

	uuidReport2, err := ioutil.ReadFile("results/" + arvadostest.CompletedContainerRequestUUID2 + ".csv")
	c.Assert(err, check.IsNil)
	c.Check(string(uuidReport2), check.Matches, "(?ms).*TOTAL,,,,,,,,,42.27031111")

	re := regexp.MustCompile(`(?ms).*supplied uuids in (.*?)\n`)
	matches := re.FindStringSubmatch(stderr.String()) // matches[1] contains a string like 'results/2020-11-02-18-57-45-aggregate-costaccounting.csv'

	aggregateCostReport, err := ioutil.ReadFile(matches[1])
	c.Assert(err, check.IsNil)

	c.Check(string(aggregateCostReport), check.Matches, "(?ms).*TOTAL,49.28334000")

	// Now move both container requests into an existing project, and then re-run
	// the analysis with the project uuid. The results should be identical.
	arv, err := arvadosclient.MakeArvadosClient()
	c.Assert(err, check.Equals, nil)

	var cr arvados.ContainerRequest
	err = arv.Update("container_requests", arvadostest.CompletedContainerRequestUUID, arvadosclient.Dict{"container_request": arvadosclient.Dict{"owner_uuid": arvadostest.AProjectUUID}}, &cr)
	c.Assert(err, check.IsNil)
	err = arv.Update("container_requests", arvadostest.CompletedContainerRequestUUID2, arvadosclient.Dict{"container_request": arvadosclient.Dict{"owner_uuid": arvadostest.AProjectUUID}}, &cr)
	c.Assert(err, check.IsNil)

	// Run costanalyzer with the project uuid
	exitcode = Command.RunCommand("costanalyzer.test", []string{"-uuid", arvadostest.AProjectUUID}, &bytes.Buffer{}, &stdout, &stderr)
	c.Check(exitcode, check.Equals, 0)
	c.Check(stderr.String(), check.Matches, "(?ms).*supplied uuids in .*")

	uuidReport, err = ioutil.ReadFile("results/" + arvadostest.CompletedContainerRequestUUID + ".csv")
	c.Assert(err, check.IsNil)
	c.Check(string(uuidReport), check.Matches, "(?ms).*TOTAL,,,,,,,,,7.01302889")

	uuidReport2, err = ioutil.ReadFile("results/" + arvadostest.CompletedContainerRequestUUID2 + ".csv")
	c.Assert(err, check.IsNil)
	c.Check(string(uuidReport2), check.Matches, "(?ms).*TOTAL,,,,,,,,,42.27031111")

	re = regexp.MustCompile(`(?ms).*supplied uuids in (.*?)\n`)
	matches = re.FindStringSubmatch(stderr.String()) // matches[1] contains a string like 'results/2020-11-02-18-57-45-aggregate-costaccounting.csv'

	aggregateCostReport, err = ioutil.ReadFile(matches[1])
	c.Assert(err, check.IsNil)

	c.Check(string(aggregateCostReport), check.Matches, "(?ms).*TOTAL,49.28334000")
}

func (*Suite) TestMultipleContainerRequestUUIDWithReuse(c *check.C) {
	var stdout, stderr bytes.Buffer
	// Run costanalyzer with 2 container request uuids
	exitcode := Command.RunCommand("costanalyzer.test", []string{"-uuid", arvadostest.CompletedDiagnosticsContainerRequest1UUID, "-uuid", arvadostest.CompletedDiagnosticsContainerRequest2UUID}, &bytes.Buffer{}, &stdout, &stderr)
	c.Check(exitcode, check.Equals, 0)
	c.Check(stderr.String(), check.Matches, "(?ms).*supplied uuids in .*")

	uuidReport, err := ioutil.ReadFile("results/" + arvadostest.CompletedDiagnosticsContainerRequest1UUID + ".csv")
	c.Assert(err, check.IsNil)
	c.Check(string(uuidReport), check.Matches, "(?ms).*TOTAL,,,,,,,,,0.00914539")

	uuidReport2, err := ioutil.ReadFile("results/" + arvadostest.CompletedDiagnosticsContainerRequest2UUID + ".csv")
	c.Assert(err, check.IsNil)
	c.Check(string(uuidReport2), check.Matches, "(?ms).*TOTAL,,,,,,,,,0.00586435")

	re := regexp.MustCompile(`(?ms).*supplied uuids in (.*?)\n`)
	matches := re.FindStringSubmatch(stderr.String()) // matches[1] contains a string like 'results/2020-11-02-18-57-45-aggregate-costaccounting.csv'

	aggregateCostReport, err := ioutil.ReadFile(matches[1])
	c.Assert(err, check.IsNil)

	c.Check(string(aggregateCostReport), check.Matches, "(?ms).*TOTAL,0.01490377")
}
