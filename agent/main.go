package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"syscall"
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
	AgentVersion string `json:"agent_version"`
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

	checkAndUpdate()

	serverURL := os.Getenv("BREWERY_SERVER_URL")
	if serverURL == "" {
		log.Fatal("BREWERY_SERVER_URL not set")
	}
	apiKey := os.Getenv("BREWERY_API_KEY")

	serial, err := getSerial()
	if err != nil {
		log.Fatalf("serial number: %v", err)
	}

	user, err := consoleUser()
	if err != nil {
		log.Fatalf("console user: %v", err)
	}

	hostname, _ := os.Hostname()
	formulas := listFormulas(user)
	casks := listCasks(user)

	req := syncRequest{
		SerialNumber: serial,
		Hostname:     hostname,
		AgentVersion: version,
		Formulas:     formulas,
		Casks:        casks,
	}

	if err := postSync(serverURL, apiKey, req); err != nil {
		log.Fatalf("sync: %v", err)
	}

	log.Printf("synced %d formulas, %d casks for %s (%s)", len(formulas), len(casks), hostname, serial)
}

func checkAndUpdate() {
	if version == "dev" {
		return
	}
	latest, err := latestRelease()
	if err != nil {
		log.Printf("auto-update: check failed: %v", err)
		return
	}
	if !isNewer(latest, version) {
		return
	}
	log.Printf("auto-update: updating %s → %s", version, latest)
	if err := selfUpdate(latest); err != nil {
		log.Printf("auto-update: failed: %v", err)
		return
	}
	exe, err := os.Executable()
	if err != nil {
		log.Printf("auto-update: restart failed: %v", err)
		return
	}
	log.Printf("auto-update: restarting as %s", latest)
	syscall.Exec(exe, os.Args, os.Environ())
}

func latestRelease() (string, error) {
	client := &http.Client{
		Timeout: 15 * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}
	resp, err := client.Head("https://github.com/cpressland/brewery/releases/latest")
	if err != nil {
		return "", err
	}
	resp.Body.Close()
	loc := resp.Header.Get("Location")
	if loc == "" {
		return "", fmt.Errorf("no Location header in redirect")
	}
	return loc[strings.LastIndex(loc, "/")+1:], nil
}

func isNewer(a, b string) bool {
	parse := func(v string) [3]int {
		v = strings.TrimPrefix(v, "v")
		parts := strings.SplitN(v, ".", 3)
		var n [3]int
		for i, p := range parts {
			if i < 3 {
				n[i], _ = strconv.Atoi(p)
			}
		}
		return n
	}
	av, bv := parse(a), parse(b)
	for i := range av {
		if av[i] != bv[i] {
			return av[i] > bv[i]
		}
	}
	return false
}

func selfUpdate(tag string) error {
	url := fmt.Sprintf(
		"https://github.com/cpressland/brewery/releases/download/%s/brewery-agent-darwin-%s",
		tag, runtime.GOARCH,
	)
	resp, err := http.Get(url)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("download returned HTTP %d", resp.StatusCode)
	}

	exe, err := os.Executable()
	if err != nil {
		return err
	}
	exe, err = filepath.EvalSymlinks(exe)
	if err != nil {
		return err
	}

	tmp := exe + ".tmp"
	f, err := os.OpenFile(tmp, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0755)
	if err != nil {
		return err
	}
	if _, err := io.Copy(f, resp.Body); err != nil {
		f.Close()
		os.Remove(tmp)
		return err
	}
	f.Close()

	return os.Rename(tmp, exe)
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

func consoleUser() (string, error) {
	out, err := exec.Command("stat", "-f", "%Su", "/dev/console").Output()
	if err != nil {
		return "", err
	}
	user := strings.TrimSpace(string(out))
	if user == "" || user == "root" {
		return "", fmt.Errorf("no user logged in at console")
	}
	return user, nil
}

func brewOutput(user string, args ...string) ([]byte, error) {
	return exec.Command("su", "-l", user, "-c", "brew "+strings.Join(args, " ")).Output()
}

func listFormulas(user string) []pkg {
	out, err := brewOutput(user, "list", "--formula", "--versions")
	if err != nil {
		if ee, ok := err.(*exec.ExitError); ok && len(ee.Stderr) > 0 {
			log.Printf("brew list --formula: %s", strings.TrimSpace(string(ee.Stderr)))
		}
	}
	pkgs := make([]pkg, 0)
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

func listCasks(user string) []pkg {
	out, err := brewOutput(user, "list", "--cask")
	if err != nil {
		if ee, ok := err.(*exec.ExitError); ok && len(ee.Stderr) > 0 {
			log.Printf("brew list --cask: %s", strings.TrimSpace(string(ee.Stderr)))
		}
	}

	prefixOut, err := brewOutput(user, "--prefix")
	if err != nil {
		log.Printf("brew --prefix: %v", err)
		return make([]pkg, 0)
	}
	caskroom := filepath.Join(strings.TrimSpace(string(prefixOut)), "Caskroom")

	pkgs := make([]pkg, 0)
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
