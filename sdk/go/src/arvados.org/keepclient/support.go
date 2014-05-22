/* Internal methods to support keepclient.go */
package keepclient

import (
	"arvados.org/streamer"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"sort"
	"strconv"
)

type keepDisk struct {
	Hostname string `json:"service_host"`
	Port     int    `json:"service_port"`
	SSL      bool   `json:"service_ssl_flag"`
	SvcType  string `json:"service_type"`
}

func (this *KeepClient) discoverKeepServers() error {
	if prx := os.Getenv("ARVADOS_KEEP_PROXY"); prx != "" {
		this.Service_roots = make([]string, 1)
		this.Service_roots[0] = prx
		this.Using_proxy = true
		return nil
	}

	// Construct request of keep disk list
	var req *http.Request
	var err error

	if req, err = http.NewRequest("GET", fmt.Sprintf("https://%s/arvados/v1/keep_services/accessible?format=json", this.ApiServer), nil); err != nil {
		return err
	}

	// Add api token header
	req.Header.Add("Authorization", fmt.Sprintf("OAuth2 %s", this.ApiToken))
	if this.External {
		req.Header.Add("X-External-Client", "1")
	}

	// Make the request
	var resp *http.Response
	if resp, err = this.Client.Do(req); err != nil {
		return err
	}

	if resp.StatusCode != 200 {
		// fall back on keep disks
		if req, err = http.NewRequest("GET", fmt.Sprintf("https://%s/arvados/v1/keep_disks", this.ApiServer), nil); err != nil {
			return err
		}
		req.Header.Add("Authorization", fmt.Sprintf("OAuth2 %s", this.ApiToken))
		if resp, err = this.Client.Do(req); err != nil {
			return err
		}
	}

	type svcList struct {
		Items []keepDisk `json:"items"`
	}

	// Decode json reply
	dec := json.NewDecoder(resp.Body)
	var m svcList
	if err := dec.Decode(&m); err != nil {
		return err
	}

	listed := make(map[string]bool)
	this.Service_roots = make([]string, 0, len(m.Items))

	for _, element := range m.Items {
		n := ""

		if element.SSL {
			n = "s"
		}

		// Construct server URL
		url := fmt.Sprintf("http%s://%s:%d", n, element.Hostname, element.Port)

		// Skip duplicates
		if !listed[url] {
			listed[url] = true
			this.Service_roots = append(this.Service_roots, url)
		}
		if element.SvcType == "proxy" {
			this.Using_proxy = true
		}
	}

	// Must be sorted for ShuffledServiceRoots() to produce consistent
	// results.
	sort.Strings(this.Service_roots)

	return nil
}

func (this KeepClient) shuffledServiceRoots(hash string) (pseq []string) {
	// Build an ordering with which to query the Keep servers based on the
	// contents of the hash.  "hash" is a hex-encoded number at least 8
	// digits (32 bits) long

	// seed used to calculate the next keep server from 'pool' to be added
	// to 'pseq'
	seed := hash

	// Keep servers still to be added to the ordering
	pool := make([]string, len(this.Service_roots))
	copy(pool, this.Service_roots)

	// output probe sequence
	pseq = make([]string, 0, len(this.Service_roots))

	// iterate while there are servers left to be assigned
	for len(pool) > 0 {

		if len(seed) < 8 {
			// ran out of digits in the seed
			if len(pseq) < (len(hash) / 4) {
				// the number of servers added to the probe
				// sequence is less than the number of 4-digit
				// slices in 'hash' so refill the seed with the
				// last 4 digits.
				seed = hash[len(hash)-4:]
			}
			seed += hash
		}

		// Take the next 8 digits (32 bytes) and interpret as an integer,
		// then modulus with the size of the remaining pool to get the next
		// selected server.
		probe, _ := strconv.ParseUint(seed[0:8], 16, 32)
		probe %= uint64(len(pool))

		// Append the selected server to the probe sequence and remove it
		// from the pool.
		pseq = append(pseq, pool[probe])
		pool = append(pool[:probe], pool[probe+1:]...)

		// Remove the digits just used from the seed
		seed = seed[8:]
	}
	return pseq
}

type uploadStatus struct {
	err             error
	url             string
	statusCode      int
	replicas_stored int
}

func (this KeepClient) uploadToKeepServer(host string, hash string, body io.ReadCloser,
	upload_status chan<- uploadStatus, expectedLength int64) {

	log.Printf("Uploading to %s", host)

	var req *http.Request
	var err error
	var url = fmt.Sprintf("%s/%s", host, hash)
	if req, err = http.NewRequest("PUT", url, nil); err != nil {
		upload_status <- uploadStatus{err, url, 0, 0}
		body.Close()
		return
	}

	if expectedLength > 0 {
		req.ContentLength = expectedLength
	}

	req.Header.Add("Authorization", fmt.Sprintf("OAuth2 %s", this.ApiToken))
	req.Header.Add("Content-Type", "application/octet-stream")

	if this.Using_proxy {
		req.Header.Add("X-Keep-Desired-Replicas", fmt.Sprint(this.Want_replicas))
	}

	req.Body = body

	var resp *http.Response
	if resp, err = this.Client.Do(req); err != nil {
		upload_status <- uploadStatus{err, url, 0, 0}
		return
	}

	rep := 1
	if xr := resp.Header.Get("X-Keep-Replicas-Stored"); xr != "" {
		fmt.Sscanf(xr, "%d", &rep)
	}

	if resp.StatusCode == http.StatusOK {
		upload_status <- uploadStatus{nil, url, resp.StatusCode, rep}
	} else {
		upload_status <- uploadStatus{errors.New(resp.Status), url, resp.StatusCode, rep}
	}
}

func (this KeepClient) putReplicas(
	hash string,
	tr *streamer.AsyncStream,
	expectedLength int64) (replicas int, err error) {

	// Calculate the ordering for uploading to servers
	sv := this.shuffledServiceRoots(hash)

	// The next server to try contacting
	next_server := 0

	// The number of active writers
	active := 0

	// Used to communicate status from the upload goroutines
	upload_status := make(chan uploadStatus)
	defer close(upload_status)

	// Desired number of replicas

	remaining_replicas := this.Want_replicas

	for remaining_replicas > 0 {
		for active < remaining_replicas {
			// Start some upload requests
			if next_server < len(sv) {
				go this.uploadToKeepServer(sv[next_server], hash, tr.MakeStreamReader(), upload_status, expectedLength)
				next_server += 1
				active += 1
			} else {
				fmt.Print(active)
				if active == 0 {
					return (this.Want_replicas - remaining_replicas), InsufficientReplicasError
				} else {
					break
				}
			}
		}

		// Now wait for something to happen.
		status := <-upload_status
		if status.statusCode == 200 {
			// good news!
			remaining_replicas -= status.replicas_stored
		} else {
			// writing to keep server failed for some reason
			log.Printf("Keep server put to %v failed with '%v'",
				status.url, status.err)
		}
		active -= 1
		log.Printf("Upload status %v %v %v", status.statusCode, remaining_replicas, active)
	}

	return this.Want_replicas, nil
}
