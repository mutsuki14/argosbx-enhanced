// Local test fixture: two independent TLS/H2 entry points, one XHTTP origin.
package main

import (
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"time"
)

func main() {
	upstream, err := url.Parse(os.Args[1])
	if err != nil {
		log.Fatal(err)
	}
	var addresses []string
	for i := 0; i < 2; i++ {
		listener, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			log.Fatal(err)
		}
		addresses = append(addresses, listener.Addr().String())
		proxy := httputil.NewSingleHostReverseProxy(upstream)
		proxy.FlushInterval = -1 * time.Millisecond
		if upstream.Scheme == "https" {
			ca, err := os.ReadFile(os.Args[5])
			if err != nil {
				log.Fatal(err)
			}
			roots := x509.NewCertPool()
			if !roots.AppendCertsFromPEM(ca) {
				log.Fatal("invalid origin CA")
			}
			proxy.Transport = &http.Transport{
				TLSClientConfig:   &tls.Config{RootCAs: roots, ServerName: "localhost", MinVersion: tls.VersionTLS12},
				ForceAttemptHTTP2: true,
			}
			proxy.ModifyResponse = func(r *http.Response) error {
				log.Printf("origin=%s response-type=%s", r.Proto, r.Header.Get("Content-Type"))
				if r.ProtoMajor != 2 {
					return fmt.Errorf("streaming origin downgraded to %s", r.Proto)
				}
				return nil
			}
		}
		server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			log.Printf("%s %s %s content-type=%s", r.Proto, r.Method, r.URL.Path, r.Header.Get("Content-Type"))
			proxy.ServeHTTP(w, r)
		})}
		go func() { log.Fatal(server.ServeTLS(listener, os.Args[2], os.Args[3])) }()
	}
	data, _ := json.Marshal(addresses)
	if err := os.WriteFile(os.Args[4], data, 0600); err != nil {
		log.Fatal(err)
	}
	select {}
}
