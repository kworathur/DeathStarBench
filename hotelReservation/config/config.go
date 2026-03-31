package config

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
)

const EnvConfigPath = "HOTEL_RESERVATION_CONFIG"

// Values holds config.json key/value settings.
type Values map[string]string

// LoadWithConfigFlag resolves the config path from CLI args or env, registers
// the -config flag, and loads the selected config file.
func LoadWithConfigFlag(args []string, defaultPath string) (Values, *string, error) {
	resolvedPath := ResolvePath(args, defaultPath)
	configPath := flag.String("config", resolvedPath, "Path to service config JSON")

	values, err := Load(resolvedPath)
	if err != nil {
		return nil, configPath, err
	}

	return values, configPath, nil
}

// ResolvePath gives CLI arguments precedence over env and env precedence over
// the default path.
func ResolvePath(args []string, defaultPath string) string {
	if path := pathFromArgs(args); path != "" {
		return path
	}
	if path := os.Getenv(EnvConfigPath); path != "" {
		return path
	}
	return defaultPath
}

// Load reads a service config file into a string map.
func Load(path string) (Values, error) {
	content, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read config %q: %w", path, err)
	}

	var values Values
	if err := json.Unmarshal(content, &values); err != nil {
		return nil, fmt.Errorf("parse config %q: %w", path, err)
	}

	return values, nil
}

func pathFromArgs(args []string) string {
	for i := 0; i < len(args); i++ {
		arg := args[i]
		switch {
		case arg == "-config" || arg == "--config":
			if i+1 < len(args) {
				return args[i+1]
			}
		case len(arg) > len("-config=") && arg[:8] == "-config=":
			return arg[8:]
		case len(arg) > len("--config=") && arg[:9] == "--config=":
			return arg[9:]
		}
	}

	return ""
}
