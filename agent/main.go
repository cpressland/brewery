package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

var version = "dev"

type pkg struct {
	Name    string  `json:"name"`
	Version *string `json:"version"`
}

type syncRequest struct {
	SerialNumber string `json:"serial_number"`
	Hostname     string `json:"hostname"`
	Formulas     []pkg  `json:"formulas"`
	Casks        []pkg  `json:"casks"`
}

func main() {
	ver := flag.Bool("version", false, "print version and exit")
	flag.Parse()
	if *ver {
		fmt.Println(version)
		return
	}

	serverURL := os.Getenv("BREWERY_SERVER_URL")
	if serverURL == "" {
		log.Fatal("BREWERY_SERVER_URL not set")
	}
	apiKey := os.Getenv("BREWERY_API_KEY")

	serial, err := getSerial()
	if err != nil {
		log.Fatalf("serial number: %v", err)
	}

	hostname, _ := os.Hostname()
	formulas := listFormulas()
	casks := listCasks()

	req := syncRequest{
		SerialNumber: serial,
		Hostname:     hostname,
		Formulas:     formulas,
		Casks:        casks,
	}

	if err := postSync(serverURL, apiKey, req); err != nil {
		log.Fatalf("sync: %v", err)
	}

	log.Printf("synced %d formulas, %d casks for %s (%s)", len(formulas), len(casks), hostname, serial)
}

func getSerial() (string, error) {
	out, err := exec.Command("system_profiler", "SPHardwareDataType", "-json").Output()
	if err != nil {
		return "", err
	}
	var data struct {
		SPHardwareDataType []struct {
			Serial string `json:"serial_number"`
		} `json:"SPHardwareDataType"`
	}
	if err := json.Unmarshal(out, &data); err != nil {
		return "", err
	}
	if len(data.SPHardwareDataType) == 0 || data.SPHardwareDataType[0].Serial == "" {
		return "", fmt.Errorf("not found in system_profiler output")
	}
	return data.SPHardwareDataType[0].Serial, nil
}

func listFormulas() []pkg {
	out, err := exec.Command("brew", "list", "--formula", "--versions").Output()
	if err != nil {
		if ee, ok := err.(*exec.ExitError); ok && len(ee.Stderr) > 0 {
			log.Printf("brew list --formula: %s", strings.TrimSpace(string(ee.Stderr)))
		}
	}
	var pkgs []pkg
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		parts := strings.Fields(line)
		if len(parts) == 0 {
			continue
		}
		p := pkg{Name: parts[0]}
		if len(parts) > 1 {
			v := parts[1]
			p.Version = &v
		}
		pkgs = append(pkgs, p)
	}
	return pkgs
}

func listCasks() []pkg {
	out, err := exec.Command("brew", "list", "--cask").Output()
	if err != nil {
		if ee, ok := err.(*exec.ExitError); ok && len(ee.Stderr) > 0 {
			log.Printf("brew list --cask: %s", strings.TrimSpace(string(ee.Stderr)))
		}
	}

	prefixOut, err := exec.Command("brew", "--prefix").Output()
	if err != nil {
		log.Printf("brew --prefix: %v", err)
		return nil
	}
	caskroom := filepath.Join(strings.TrimSpace(string(prefixOut)), "Caskroom")

	var pkgs []pkg
	for _, name := range strings.Fields(string(out)) {
		p := pkg{Name: name}
		if v := caskVersion(caskroom, name); v != "" {
			p.Version = &v
		}
		pkgs = append(pkgs, p)
	}
	return pkgs
}

func caskVersion(caskroom, name string) string {
	entries, err := os.ReadDir(filepath.Join(caskroom, name))
	if err != nil {
		return ""
	}
	for _, e := range entries {
		if e.IsDir() && !strings.HasPrefix(e.Name(), ".") {
			return e.Name()
		}
	}
	return ""
}

func postSync(serverURL, apiKey string, req syncRequest) error {
	body, err := json.Marshal(req)
	if err != nil {
		return err
	}

	url := strings.TrimRight(serverURL, "/") + "/api/v1/sync"
	r, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return err
	}
	r.Header.Set("Content-Type", "application/json")
	if apiKey != "" {
		r.Header.Set("Authorization", "Bearer "+apiKey)
	}

	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(r)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("server returned HTTP %d", resp.StatusCode)
	}
	return nil
}
