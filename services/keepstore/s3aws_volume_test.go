// Copyright (C) The Arvados Authors. All rights reserved.
//
// SPDX-License-Identifier: AGPL-3.0

package main

import (
	"bytes"
	"context"
	"crypto/md5"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"time"

	"git.arvados.org/arvados.git/sdk/go/arvados"
	"git.arvados.org/arvados.git/sdk/go/ctxlog"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/s3manager"

	"github.com/johannesboyne/gofakes3"
	"github.com/johannesboyne/gofakes3/backend/s3mem"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/sirupsen/logrus"
	check "gopkg.in/check.v1"
)

const (
	S3AWSTestBucketName = "testbucket"
)

type s3AWSFakeClock struct {
	now *time.Time
}

func (c *s3AWSFakeClock) Now() time.Time {
	if c.now == nil {
		return time.Now().UTC()
	}
	return c.now.UTC()
}

func (c *s3AWSFakeClock) Since(t time.Time) time.Duration {
	return c.Now().Sub(t)
}

var _ = check.Suite(&StubbedS3AWSSuite{})

var srv httptest.Server

type StubbedS3AWSSuite struct {
	s3server *httptest.Server
	metadata *httptest.Server
	cluster  *arvados.Cluster
	handler  *handler
	volumes  []*TestableS3AWSVolume
}

func (s *StubbedS3AWSSuite) SetUpTest(c *check.C) {
	s.s3server = nil
	s.metadata = nil
	s.cluster = testCluster(c)
	s.cluster.Volumes = map[string]arvados.Volume{
		"zzzzz-nyw5e-000000000000000": {Driver: "S3"},
		"zzzzz-nyw5e-111111111111111": {Driver: "S3"},
	}
	s.handler = &handler{}
}

func (s *StubbedS3AWSSuite) TestGeneric(c *check.C) {
	DoGenericVolumeTests(c, false, func(t TB, cluster *arvados.Cluster, volume arvados.Volume, logger logrus.FieldLogger, metrics *volumeMetricsVecs) TestableVolume {
		// Use a negative raceWindow so s3test's 1-second
		// timestamp precision doesn't confuse fixRace.
		return s.newTestableVolume(c, cluster, volume, metrics, -2*time.Second)
	})
}

func (s *StubbedS3AWSSuite) TestGenericReadOnly(c *check.C) {
	DoGenericVolumeTests(c, true, func(t TB, cluster *arvados.Cluster, volume arvados.Volume, logger logrus.FieldLogger, metrics *volumeMetricsVecs) TestableVolume {
		return s.newTestableVolume(c, cluster, volume, metrics, -2*time.Second)
	})
}

func (s *StubbedS3AWSSuite) TestIndex(c *check.C) {
	v := s.newTestableVolume(c, s.cluster, arvados.Volume{Replication: 2}, newVolumeMetricsVecs(prometheus.NewRegistry()), 0)
	v.IndexPageSize = 3
	for i := 0; i < 256; i++ {
		v.PutRaw(fmt.Sprintf("%02x%030x", i, i), []byte{102, 111, 111})
	}
	for _, spec := range []struct {
		prefix      string
		expectMatch int
	}{
		{"", 256},
		{"c", 16},
		{"bc", 1},
		{"abc", 0},
	} {
		buf := new(bytes.Buffer)
		err := v.IndexTo(spec.prefix, buf)
		c.Check(err, check.IsNil)

		idx := bytes.SplitAfter(buf.Bytes(), []byte{10})
		c.Check(len(idx), check.Equals, spec.expectMatch+1)
		c.Check(len(idx[len(idx)-1]), check.Equals, 0)
	}
}

func (s *StubbedS3AWSSuite) TestSignature(c *check.C) {
	var header http.Header
	stub := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		header = r.Header
	}))
	defer stub.Close()

	// The aws-sdk-go-v2 driver only supports S3 V4 signatures. S3 v2 signatures are being phased out
	// as of June 24, 2020. Cf. https://forums.aws.amazon.com/ann.jspa?annID=5816
	vol := S3AWSVolume{
		S3VolumeDriverParameters: arvados.S3VolumeDriverParameters{
			AccessKey: "xxx",
			SecretKey: "xxx",
			Endpoint:  stub.URL,
			Region:    "test-region-1",
			Bucket:    "test-bucket-name",
		},
		cluster: s.cluster,
		logger:  ctxlog.TestLogger(c),
		metrics: newVolumeMetricsVecs(prometheus.NewRegistry()),
	}
	err := vol.check("")
	// Our test S3 server uses the older 'Path Style'
	vol.bucket.svc.ForcePathStyle = true

	c.Check(err, check.IsNil)
	err = vol.Put(context.Background(), "acbd18db4cc2f85cedef654fccc4a4d8", []byte("foo"))
	c.Check(err, check.IsNil)
	c.Check(header.Get("Authorization"), check.Matches, `AWS4-HMAC-SHA256 .*`)
}

func (s *StubbedS3AWSSuite) TestIAMRoleCredentials(c *check.C) {
	s.metadata = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		upd := time.Now().UTC().Add(-time.Hour).Format(time.RFC3339)
		exp := time.Now().UTC().Add(time.Hour).Format(time.RFC3339)
		// Literal example from
		// https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/iam-roles-for-amazon-ec2.html#instance-metadata-security-credentials
		// but with updated timestamps
		io.WriteString(w, `{"Code":"Success","LastUpdated":"`+upd+`","Type":"AWS-HMAC","AccessKeyId":"ASIAIOSFODNN7EXAMPLE","SecretAccessKey":"wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY","Token":"token","Expiration":"`+exp+`"}`)
	}))
	defer s.metadata.Close()

	v := &S3AWSVolume{
		S3VolumeDriverParameters: arvados.S3VolumeDriverParameters{
			IAMRole:  s.metadata.URL + "/latest/api/token",
			Endpoint: "http://localhost:12345",
			Region:   "test-region-1",
			Bucket:   "test-bucket-name",
		},
		cluster: s.cluster,
		logger:  ctxlog.TestLogger(c),
		metrics: newVolumeMetricsVecs(prometheus.NewRegistry()),
	}
	err := v.check(s.metadata.URL + "/latest")
	c.Check(err, check.IsNil)
	creds, err := v.bucket.svc.Client.Config.Credentials.Retrieve(context.Background())
	c.Check(err, check.IsNil)
	c.Check(creds.AccessKeyID, check.Equals, "ASIAIOSFODNN7EXAMPLE")
	c.Check(creds.SecretAccessKey, check.Equals, "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")

	s.metadata = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))
	deadv := &S3AWSVolume{
		S3VolumeDriverParameters: arvados.S3VolumeDriverParameters{
			IAMRole:  s.metadata.URL + "/fake-metadata/test-role",
			Endpoint: "http://localhost:12345",
			Region:   "test-region-1",
			Bucket:   "test-bucket-name",
		},
		cluster: s.cluster,
		logger:  ctxlog.TestLogger(c),
		metrics: newVolumeMetricsVecs(prometheus.NewRegistry()),
	}
	err = deadv.check(s.metadata.URL + "/latest")
	c.Check(err, check.IsNil)
	_, err = deadv.bucket.svc.Client.Config.Credentials.Retrieve(context.Background())
	c.Check(err, check.ErrorMatches, `(?s).*EC2RoleRequestError: no EC2 instance role found.*`)
	c.Check(err, check.ErrorMatches, `(?s).*404.*`)
}

func (s *StubbedS3AWSSuite) TestStats(c *check.C) {
	v := s.newTestableVolume(c, s.cluster, arvados.Volume{Replication: 2}, newVolumeMetricsVecs(prometheus.NewRegistry()), 5*time.Minute)
	stats := func() string {
		buf, err := json.Marshal(v.InternalStats())
		c.Check(err, check.IsNil)
		return string(buf)
	}

	c.Check(stats(), check.Matches, `.*"Ops":0,.*`)

	loc := "acbd18db4cc2f85cedef654fccc4a4d8"
	_, err := v.Get(context.Background(), loc, make([]byte, 3))
	c.Check(err, check.NotNil)
	c.Check(stats(), check.Matches, `.*"Ops":[^0],.*`)
	c.Check(stats(), check.Matches, `.*"s3.requestFailure 404 NoSuchKey[^"]*":[^0].*`)
	c.Check(stats(), check.Matches, `.*"InBytes":0,.*`)

	err = v.Put(context.Background(), loc, []byte("foo"))
	c.Check(err, check.IsNil)
	c.Check(stats(), check.Matches, `.*"OutBytes":3,.*`)
	c.Check(stats(), check.Matches, `.*"PutOps":2,.*`)

	_, err = v.Get(context.Background(), loc, make([]byte, 3))
	c.Check(err, check.IsNil)
	_, err = v.Get(context.Background(), loc, make([]byte, 3))
	c.Check(err, check.IsNil)
	c.Check(stats(), check.Matches, `.*"InBytes":6,.*`)
}

type s3AWSBlockingHandler struct {
	requested chan *http.Request
	unblock   chan struct{}
}

func (h *s3AWSBlockingHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method == "PUT" && !strings.Contains(strings.Trim(r.URL.Path, "/"), "/") {
		// Accept PutBucket ("PUT /bucketname/"), called by
		// newTestableVolume
		return
	}
	if h.requested != nil {
		h.requested <- r
	}
	if h.unblock != nil {
		<-h.unblock
	}
	http.Error(w, "nothing here", http.StatusNotFound)
}

func (s *StubbedS3AWSSuite) TestGetContextCancel(c *check.C) {
	loc := "acbd18db4cc2f85cedef654fccc4a4d8"
	buf := make([]byte, 3)

	s.testContextCancel(c, func(ctx context.Context, v *TestableS3AWSVolume) error {
		_, err := v.Get(ctx, loc, buf)
		return err
	})
}

func (s *StubbedS3AWSSuite) TestCompareContextCancel(c *check.C) {
	loc := "acbd18db4cc2f85cedef654fccc4a4d8"
	buf := []byte("bar")

	s.testContextCancel(c, func(ctx context.Context, v *TestableS3AWSVolume) error {
		return v.Compare(ctx, loc, buf)
	})
}

func (s *StubbedS3AWSSuite) TestPutContextCancel(c *check.C) {
	loc := "acbd18db4cc2f85cedef654fccc4a4d8"
	buf := []byte("foo")

	s.testContextCancel(c, func(ctx context.Context, v *TestableS3AWSVolume) error {
		return v.Put(ctx, loc, buf)
	})
}

func (s *StubbedS3AWSSuite) testContextCancel(c *check.C, testFunc func(context.Context, *TestableS3AWSVolume) error) {
	handler := &s3AWSBlockingHandler{}
	s.s3server = httptest.NewServer(handler)
	defer s.s3server.Close()

	v := s.newTestableVolume(c, s.cluster, arvados.Volume{Replication: 2}, newVolumeMetricsVecs(prometheus.NewRegistry()), 5*time.Minute)

	ctx, cancel := context.WithCancel(context.Background())

	handler.requested = make(chan *http.Request)
	handler.unblock = make(chan struct{})
	defer close(handler.unblock)

	doneFunc := make(chan struct{})
	go func() {
		err := testFunc(ctx, v)
		c.Check(err, check.Equals, context.Canceled)
		close(doneFunc)
	}()

	timeout := time.After(10 * time.Second)

	// Wait for the stub server to receive a request, meaning
	// Get() is waiting for an s3 operation.
	select {
	case <-timeout:
		c.Fatal("timed out waiting for test func to call our handler")
	case <-doneFunc:
		c.Fatal("test func finished without even calling our handler!")
	case <-handler.requested:
	}

	cancel()

	select {
	case <-timeout:
		c.Fatal("timed out")
	case <-doneFunc:
	}
}

func (s *StubbedS3AWSSuite) TestBackendStates(c *check.C) {
	s.cluster.Collections.BlobTrashLifetime.Set("1h")
	s.cluster.Collections.BlobSigningTTL.Set("1h")

	v := s.newTestableVolume(c, s.cluster, arvados.Volume{Replication: 2}, newVolumeMetricsVecs(prometheus.NewRegistry()), 5*time.Minute)
	var none time.Time

	putS3Obj := func(t time.Time, key string, data []byte) {
		if t == none {
			return
		}
		v.serverClock.now = &t
		uploader := s3manager.NewUploaderWithClient(v.bucket.svc)
		_, err := uploader.UploadWithContext(context.Background(), &s3manager.UploadInput{
			Bucket: aws.String(v.bucket.bucket),
			Key:    aws.String(key),
			Body:   bytes.NewReader(data),
		})
		if err != nil {
			panic(err)
		}
		v.serverClock.now = nil
		_, err = v.Head(key)
		if err != nil {
			panic(err)
		}
	}

	t0 := time.Now()
	nextKey := 0
	for _, scenario := range []struct {
		label               string
		dataT               time.Time
		recentT             time.Time
		trashT              time.Time
		canGet              bool
		canTrash            bool
		canGetAfterTrash    bool
		canUntrash          bool
		haveTrashAfterEmpty bool
		freshAfterEmpty     bool
	}{
		{
			"No related objects",
			none, none, none,
			false, false, false, false, false, false,
		},
		{
			// Stored by older version, or there was a
			// race between EmptyTrash and Put: Trash is a
			// no-op even though the data object is very
			// old
			"No recent/X",
			t0.Add(-48 * time.Hour), none, none,
			true, true, true, false, false, false,
		},
		{
			"Not trash, but old enough to be eligible for trash",
			t0.Add(-24 * time.Hour), t0.Add(-2 * time.Hour), none,
			true, true, false, false, false, false,
		},
		{
			"Not trash, and not old enough to be eligible for trash",
			t0.Add(-24 * time.Hour), t0.Add(-30 * time.Minute), none,
			true, true, true, false, false, false,
		},
		{
			"Trashed + untrashed copies exist, due to recent race between Trash and Put",
			t0.Add(-24 * time.Hour), t0.Add(-3 * time.Minute), t0.Add(-2 * time.Minute),
			true, true, true, true, true, false,
		},
		{
			"Trashed + untrashed copies exist, trash nearly eligible for deletion: prone to Trash race",
			t0.Add(-24 * time.Hour), t0.Add(-12 * time.Hour), t0.Add(-59 * time.Minute),
			true, false, true, true, true, false,
		},
		{
			"Trashed + untrashed copies exist, trash is eligible for deletion: prone to Trash race",
			t0.Add(-24 * time.Hour), t0.Add(-12 * time.Hour), t0.Add(-61 * time.Minute),
			true, false, true, true, false, false,
		},
		{
			"Trashed + untrashed copies exist, due to old race between Put and unfinished Trash: emptying trash is unsafe",
			t0.Add(-24 * time.Hour), t0.Add(-12 * time.Hour), t0.Add(-12 * time.Hour),
			true, false, true, true, true, true,
		},
		{
			"Trashed + untrashed copies exist, used to be unsafe to empty, but since made safe by fixRace+Touch",
			t0.Add(-time.Second), t0.Add(-time.Second), t0.Add(-12 * time.Hour),
			true, true, true, true, false, false,
		},
		{
			"Trashed + untrashed copies exist because Trash operation was interrupted (no race)",
			t0.Add(-24 * time.Hour), t0.Add(-24 * time.Hour), t0.Add(-12 * time.Hour),
			true, false, true, true, false, false,
		},
		{
			"Trash, not yet eligible for deletion",
			none, t0.Add(-12 * time.Hour), t0.Add(-time.Minute),
			false, false, false, true, true, false,
		},
		{
			"Trash, not yet eligible for deletion, prone to races",
			none, t0.Add(-12 * time.Hour), t0.Add(-59 * time.Minute),
			false, false, false, true, true, false,
		},
		{
			"Trash, eligible for deletion",
			none, t0.Add(-12 * time.Hour), t0.Add(-2 * time.Hour),
			false, false, false, true, false, false,
		},
		{
			"Erroneously trashed during a race, detected before BlobTrashLifetime",
			none, t0.Add(-30 * time.Minute), t0.Add(-29 * time.Minute),
			true, false, true, true, true, false,
		},
		{
			"Erroneously trashed during a race, rescue during EmptyTrash despite reaching BlobTrashLifetime",
			none, t0.Add(-90 * time.Minute), t0.Add(-89 * time.Minute),
			true, false, true, true, true, false,
		},
		{
			"Trashed copy exists with no recent/* marker (cause unknown); repair by untrashing",
			none, none, t0.Add(-time.Minute),
			false, false, false, true, true, true,
		},
	} {
		c.Log("Scenario: ", scenario.label)

		// We have a few tests to run for each scenario, and
		// the tests are expected to change state. By calling
		// this setup func between tests, we (re)create the
		// scenario as specified, using a new unique block
		// locator to prevent interference from previous
		// tests.

		setupScenario := func() (string, []byte) {
			nextKey++
			blk := []byte(fmt.Sprintf("%d", nextKey))
			loc := fmt.Sprintf("%x", md5.Sum(blk))
			c.Log("\t", loc)
			putS3Obj(scenario.dataT, loc, blk)
			putS3Obj(scenario.recentT, "recent/"+loc, nil)
			putS3Obj(scenario.trashT, "trash/"+loc, blk)
			v.serverClock.now = &t0
			return loc, blk
		}

		// Check canGet
		loc, blk := setupScenario()
		buf := make([]byte, len(blk))
		_, err := v.Get(context.Background(), loc, buf)
		c.Check(err == nil, check.Equals, scenario.canGet)
		if err != nil {
			c.Check(os.IsNotExist(err), check.Equals, true)
		}

		// Call Trash, then check canTrash and canGetAfterTrash
		loc, _ = setupScenario()
		err = v.Trash(loc)
		c.Check(err == nil, check.Equals, scenario.canTrash)
		_, err = v.Get(context.Background(), loc, buf)
		c.Check(err == nil, check.Equals, scenario.canGetAfterTrash)
		if err != nil {
			c.Check(os.IsNotExist(err), check.Equals, true)
		}

		// Call Untrash, then check canUntrash
		loc, _ = setupScenario()
		err = v.Untrash(loc)
		c.Check(err == nil, check.Equals, scenario.canUntrash)
		if scenario.dataT != none || scenario.trashT != none {
			// In all scenarios where the data exists, we
			// should be able to Get after Untrash --
			// regardless of timestamps, errors, race
			// conditions, etc.
			_, err = v.Get(context.Background(), loc, buf)
			c.Check(err, check.IsNil)
		}

		// Call EmptyTrash, then check haveTrashAfterEmpty and
		// freshAfterEmpty
		loc, _ = setupScenario()
		v.EmptyTrash()
		_, err = v.Head("trash/" + loc)
		c.Check(err == nil, check.Equals, scenario.haveTrashAfterEmpty)
		if scenario.freshAfterEmpty {
			t, err := v.Mtime(loc)
			c.Check(err, check.IsNil)
			// new mtime must be current (with an
			// allowance for 1s timestamp precision)
			c.Check(t.After(t0.Add(-time.Second)), check.Equals, true)
		}

		// Check for current Mtime after Put (applies to all
		// scenarios)
		loc, blk = setupScenario()
		err = v.Put(context.Background(), loc, blk)
		c.Check(err, check.IsNil)
		t, err := v.Mtime(loc)
		c.Check(err, check.IsNil)
		c.Check(t.After(t0.Add(-time.Second)), check.Equals, true)
	}
}

type TestableS3AWSVolume struct {
	*S3AWSVolume
	server      *httptest.Server
	c           *check.C
	serverClock *s3AWSFakeClock
}

type LogrusLog struct {
	log *logrus.FieldLogger
}

func (l LogrusLog) Print(level gofakes3.LogLevel, v ...interface{}) {
	switch level {
	case gofakes3.LogErr:
		(*l.log).Errorln(v...)
	case gofakes3.LogWarn:
		(*l.log).Warnln(v...)
	case gofakes3.LogInfo:
		(*l.log).Infoln(v...)
	default:
		panic("unknown level")
	}
}

func (s *StubbedS3AWSSuite) newTestableVolume(c *check.C, cluster *arvados.Cluster, volume arvados.Volume, metrics *volumeMetricsVecs, raceWindow time.Duration) *TestableS3AWSVolume {

	clock := &s3AWSFakeClock{}
	// fake s3
	backend := s3mem.New(s3mem.WithTimeSource(clock))

	// To enable GoFakeS3 debug logging, pass logger to gofakes3.WithLogger()
	/* logger := new(LogrusLog)
	ctxLogger := ctxlog.FromContext(context.Background())
	logger.log = &ctxLogger */
	faker := gofakes3.New(backend, gofakes3.WithTimeSource(clock), gofakes3.WithLogger(nil), gofakes3.WithTimeSkewLimit(0))
	srv := httptest.NewServer(faker.Server())

	endpoint := srv.URL
	if s.s3server != nil {
		endpoint = s.s3server.URL
	}

	iamRole, accessKey, secretKey := "", "xxx", "xxx"
	if s.metadata != nil {
		iamRole, accessKey, secretKey = s.metadata.URL+"/fake-metadata/test-role", "", ""
	}

	v := &TestableS3AWSVolume{
		S3AWSVolume: &S3AWSVolume{
			S3VolumeDriverParameters: arvados.S3VolumeDriverParameters{
				IAMRole:            iamRole,
				AccessKey:          accessKey,
				SecretKey:          secretKey,
				Bucket:             S3AWSTestBucketName,
				Endpoint:           endpoint,
				Region:             "test-region-1",
				LocationConstraint: true,
				UnsafeDelete:       true,
				IndexPageSize:      1000,
			},
			cluster: cluster,
			volume:  volume,
			logger:  ctxlog.TestLogger(c),
			metrics: metrics,
		},
		c:           c,
		server:      srv,
		serverClock: clock,
	}
	c.Assert(v.S3AWSVolume.check(""), check.IsNil)
	// Our test S3 server uses the older 'Path Style'
	v.S3AWSVolume.bucket.svc.ForcePathStyle = true
	// Create the testbucket
	input := &s3.CreateBucketInput{
		Bucket: aws.String(S3AWSTestBucketName),
	}
	req := v.S3AWSVolume.bucket.svc.CreateBucketRequest(input)
	_, err := req.Send(context.Background())
	c.Assert(err, check.IsNil)
	// We couldn't set RaceWindow until now because check()
	// rejects negative values.
	v.S3AWSVolume.RaceWindow = arvados.Duration(raceWindow)
	return v
}

// PutRaw skips the ContentMD5 test
func (v *TestableS3AWSVolume) PutRaw(loc string, block []byte) {

	r := NewCountingReader(bytes.NewReader(block), v.bucket.stats.TickOutBytes)

	uploader := s3manager.NewUploaderWithClient(v.bucket.svc, func(u *s3manager.Uploader) {
		u.PartSize = 5 * 1024 * 1024
		u.Concurrency = 13
	})

	_, err := uploader.Upload(&s3manager.UploadInput{
		Bucket: aws.String(v.bucket.bucket),
		Key:    aws.String(loc),
		Body:   r,
	})
	if err != nil {
		v.logger.Printf("PutRaw: %s: %+v", loc, err)
	}

	empty := bytes.NewReader([]byte{})
	_, err = uploader.Upload(&s3manager.UploadInput{
		Bucket: aws.String(v.bucket.bucket),
		Key:    aws.String("recent/" + loc),
		Body:   empty,
	})
	if err != nil {
		v.logger.Printf("PutRaw: recent/%s: %+v", loc, err)
	}
}

// TouchWithDate turns back the clock while doing a Touch(). We assume
// there are no other operations happening on the same s3test server
// while we do this.
func (v *TestableS3AWSVolume) TouchWithDate(locator string, lastPut time.Time) {
	v.serverClock.now = &lastPut

	uploader := s3manager.NewUploaderWithClient(v.bucket.svc)
	empty := bytes.NewReader([]byte{})
	_, err := uploader.UploadWithContext(context.Background(), &s3manager.UploadInput{
		Bucket: aws.String(v.bucket.bucket),
		Key:    aws.String("recent/" + locator),
		Body:   empty,
	})
	if err != nil {
		panic(err)
	}

	v.serverClock.now = nil
}

func (v *TestableS3AWSVolume) Teardown() {
	v.server.Close()
}

func (v *TestableS3AWSVolume) ReadWriteOperationLabelValues() (r, w string) {
	return "get", "put"
}
