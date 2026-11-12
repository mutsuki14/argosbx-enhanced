// Local test fixture: two independent TLS/H2 entry points, one XHTTP origin.
package main

import (
    "encoding/json"
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
    if err != nil { log.Fatal(err) }
    var addresses []string
    for i := 0; i < 2; i++ {
        listener, err := net.Listen("tcp", "127.0.0.1:0")
        if err != nil { log.Fatal(err) }
        addresses = append(addresses, listener.Addr().String())
        proxy := httputil.NewSingleHostReverseProxy(upstream)
        proxy.FlushInterval = -1 * time.Millisecond
        server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            log.Printf("%s %s %s", r.Proto, r.Method, r.URL.Path)
            proxy.ServeHTTP(w, r)
        })}
        go func() { log.Fatal(server.ServeTLS(listener, os.Args[2], os.Args[3])) }()
    }
    data, _ := json.Marshal(addresses)
    if err := os.WriteFile(os.Args[4], data, 0600); err != nil { log.Fatal(err) }
    select {}
}
