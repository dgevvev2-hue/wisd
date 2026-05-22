package main

import (
	"crypto/tls"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
)

type headers []string

func (h *headers) String() string { return strings.Join(*h, ", ") }
func (h *headers) Set(v string) error {
	*h = append(*h, v)
	return nil
}

func main() {
	var out string
	var ua string
	var strict bool
	var hs headers
	flag.StringVar(&out, "O", "", "output file")
	flag.StringVar(&ua, "U", "", "user agent")
	flag.StringVar(&ua, "user-agent", "", "user agent")
	flag.BoolVar(&strict, "strict-tls", false, "verify TLS certificates")
	flag.Var(&hs, "header", "HTTP header")
	flag.Parse()
	if flag.NArg() != 1 {
		fmt.Fprintln(os.Stderr, "usage: rwget [-O file] [-U ua] [--header 'K: V'] url")
		os.Exit(2)
	}
	req, err := http.NewRequest("GET", flag.Arg(0), nil)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	if ua != "" {
		req.Header.Set("User-Agent", ua)
	}
	for _, h := range hs {
		k, v, ok := strings.Cut(h, ":")
		if !ok {
			continue
		}
		req.Header.Set(strings.TrimSpace(k), strings.TrimSpace(v))
	}
	if req.Header.Get("User-Agent") == "" {
		req.Header.Set("User-Agent", "rwget/1.0")
	}
	tr := &http.Transport{TLSClientConfig: &tls.Config{InsecureSkipVerify: !strict}}
	client := &http.Client{Timeout: 45 * time.Second, Transport: tr}
	resp, err := client.Do(req)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		fmt.Fprintln(os.Stderr, resp.Status)
		os.Exit(1)
	}
	var w io.Writer = os.Stdout
	var f *os.File
	if out != "" && out != "-" {
		f, err = os.Create(out)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		defer f.Close()
		w = f
	}
	if _, err = io.Copy(w, resp.Body); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
