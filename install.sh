#!/usr/bin/env bash
#
# install.sh - Installer for PageDistiller Hermes Agent plugin & library
#
# Usage:
#   ./install.sh [OPTIONS]
#
# Run './install.sh --help' for documentation and options.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
CUSTOM_VENV=""
CUSTOM_HERMES_BIN=""
EDITABLE=false
SYMLINK=false
SKIP_ENABLE=false
UNINSTALL=false

# Formatting helpers
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    BOLD='\033[1m'
    GREEN='\033[0;32m'
    BLUE='\033[0;34m'
    YELLOW='\033[0;33m'
    RED='\033[0;31m'
    NC='\033[0m'
else
    BOLD=''
    GREEN=''
    BLUE=''
    YELLOW=''
    RED=''
    NC=''
fi

log_info()  { echo -e "${BLUE}[i]${NC} $*"; }
log_ok()    { echo -e "${GREEN}[✓]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
log_error() { echo -e "${RED}[✗]${NC} $*" >&2; }

show_help() {
    cat << 'HELP'
PageDistiller Hermes Plugin Installer

SYNOPSIS
    ./install.sh [OPTIONS]

DESCRIPTION
    Installs PageDistiller into your local Hermes Agent environment.
    This script automates:
      1. Discovering the Hermes Python virtual environment.
      2. Installing the 'pagedistiller' package and dependencies into that venv.
      3. Deploying the plugin to ~/.hermes/plugins/web/pagedistiller/
         (the user plugin directory, safe from hermes update overwrites).
      4. Enabling the plugin (hermes plugins enable web/pagedistiller).
      5. Setting 'web.extract_backend: pagedistiller' in Hermes config.
      6. Verifying that the backend resolves cleanly in Hermes.

OPTIONS
    -h, --help              Show this help message and exit.
    -e, --editable          Install in editable mode (pip install -e .) and
                            symlink the plugin directory for live development.
    -s, --symlink           Symlink the plugin folder instead of copying it
                            (automatically set if -e / --editable is used).
    --no-enable             Install package and plugin files, but skip enabling
                            the plugin and configuring web.extract_backend.
    --uninstall             Uninstall pagedistiller from Hermes, remove the
                            plugin, and unset web.extract_backend in config.
    --venv PATH             Explicit path to the Hermes Python virtual environment.
    --hermes-home PATH      Explicit path to Hermes home directory (default: ~/.hermes).
    --hermes-bin PATH       Explicit path to the 'hermes' CLI executable.

EXAMPLES
    # Standard installation
    ./install.sh

    # Developer installation (live edit package and plugin)
    ./install.sh --editable

    # Uninstall from Hermes
    ./install.sh --uninstall

HELP
}

# Parse command line options
while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
        -e|--editable)
            EDITABLE=true
            SYMLINK=true
            shift
            ;;
        -s|--symlink)
            SYMLINK=true
            shift
            ;;
        --no-enable)
            SKIP_ENABLE=true
            shift
            ;;
        --uninstall)
            UNINSTALL=true
            shift
            ;;
        --venv)
            if [ $# -lt 2 ]; then
                log_error "--venv requires a path argument"
                exit 1
            fi
            CUSTOM_VENV="$2"
            shift 2
            ;;
        --hermes-home)
            if [ $# -lt 2 ]; then
                log_error "--hermes-home requires a path argument"
                exit 1
            fi
            HERMES_HOME="$2"
            shift 2
            ;;
        --hermes-bin)
            if [ $# -lt 2 ]; then
                log_error "--hermes-bin requires a path argument"
                exit 1
            fi
            CUSTOM_HERMES_BIN="$2"
            shift 2
            ;;
        *)
            log_error "Unknown option: $1"
            echo "Run '$0 --help' for usage information." >&2
            exit 1
            ;;
    esac
done

find_hermes_python() {
    if [ -n "$CUSTOM_VENV" ]; then
        if [ -x "$CUSTOM_VENV/bin/python" ]; then
            echo "$CUSTOM_VENV/bin/python"
            return 0
        elif [ -x "$CUSTOM_VENV" ]; then
            echo "$CUSTOM_VENV"
            return 0
        fi
        log_error "Python binary not found at $CUSTOM_VENV"
        return 1
    fi

    # 1. Check standard Hermes venv path
    if [ -x "$HERMES_HOME/hermes-agent/venv/bin/python" ]; then
        echo "$HERMES_HOME/hermes-agent/venv/bin/python"
        return 0
    fi

    # 2. Extract python path from hermes launcher script if available
    local hermes_cmd="${CUSTOM_HERMES_BIN:-}"
    if [ -z "$hermes_cmd" ] && command -v hermes >/dev/null 2>&1; then
        hermes_cmd=$(command -v hermes)
    fi

    if [ -n "$hermes_cmd" ] && [ -f "$hermes_cmd" ]; then
        local py_from_script
        py_from_script=$(grep -E 'exec "([^"]*python)"' "$hermes_cmd" 2>/dev/null | sed -E 's/.*exec "([^"]*)".*/\1/' || true)
        if [ -n "$py_from_script" ] && [ -x "$py_from_script" ]; then
            echo "$py_from_script"
            return 0
        fi
    fi

    # 3. Check ~/.local/bin/hermes
    if [ -f "$HOME/.local/bin/hermes" ]; then
        local py_from_local
        py_from_local=$(grep -E 'exec "([^"]*python)"' "$HOME/.local/bin/hermes" 2>/dev/null | sed -E 's/.*exec "([^"]*)".*/\1/' || true)
        if [ -n "$py_from_local" ] && [ -x "$py_from_local" ]; then
            echo "$py_from_local"
            return 0
        fi
    fi

    return 1
}

find_hermes_bin() {
    if [ -n "$CUSTOM_HERMES_BIN" ] && [ -x "$CUSTOM_HERMES_BIN" ]; then
        echo "$CUSTOM_HERMES_BIN"
        return 0
    fi
    if command -v hermes >/dev/null 2>&1; then
        command -v hermes
        return 0
    fi
    if [ -x "$HERMES_HOME/bin/hermes" ]; then
        echo "$HERMES_HOME/bin/hermes"
        return 0
    fi
    if [ -x "$HOME/.local/bin/hermes" ]; then
        echo "$HOME/.local/bin/hermes"
        return 0
    fi
    return 1
}

do_uninstall() {
    echo -e "${BOLD}PageDistiller Uninstaller${NC}\n"

    local target_plugin_dir="$HERMES_HOME/plugins/web/pagedistiller"
    if [ -e "$target_plugin_dir" ] || [ -L "$target_plugin_dir" ]; then
        log_info "Removing plugin from $target_plugin_dir..."
        rm -rf "$target_plugin_dir"
        log_ok "Removed plugin directory."
        rmdir "$HERMES_HOME/plugins/web" 2>/dev/null || true
        rmdir "$HERMES_HOME/plugins" 2>/dev/null || true
    else
        log_info "Plugin directory $target_plugin_dir not found."
    fi

    local hermes_bin
    if hermes_bin=$(find_hermes_bin); then
        log_info "Resetting Hermes plugin state and config..."
        "$hermes_bin" plugins disable web/pagedistiller >/dev/null 2>&1 || true
        "$hermes_bin" config unset web.extract_backend >/dev/null 2>&1 || true
        log_ok "Reset Hermes configuration."
    fi

    local hermes_py
    if hermes_py=$(find_hermes_python); then
        local hermes_pip="$(dirname "$hermes_py")/pip"
        if [ -x "$hermes_pip" ]; then
            log_info "Uninstalling pagedistiller package from Hermes venv..."
            "$hermes_pip" uninstall -y pagedistiller >/dev/null 2>&1 || true
            log_ok "Uninstalled pagedistiller package."
        fi
    fi

    echo ""
    log_ok "PageDistiller successfully uninstalled from Hermes."
}

do_install() {
    echo -e "${BOLD}PageDistiller Installer for Hermes Agent${NC}\n"

    local hermes_py
    if ! hermes_py=$(find_hermes_python); then
        log_error "Could not find Hermes Python virtual environment."
        log_error "Please provide the path using --venv <path> or ensure Hermes is installed."
        exit 1
    fi
    local hermes_pip="$(dirname "$hermes_py")/pip"
    if [ ! -x "$hermes_pip" ]; then
        log_error "Could not find pip at $hermes_pip"
        exit 1
    fi

    log_info "Hermes Python: $hermes_py"
    log_info "Hermes Home:   $HERMES_HOME"

    # Step 1: Install package into Hermes venv
    local pip_cmd=("$hermes_pip" "install")
    if [ "$EDITABLE" = true ]; then
        pip_cmd+=("-e")
        log_info "Installing pagedistiller in editable mode into Hermes venv..."
    else
        log_info "Installing pagedistiller into Hermes venv..."
    fi
    pip_cmd+=("$SCRIPT_DIR")

    "${pip_cmd[@]}"
    log_ok "Installed pagedistiller Python package."

    # Step 2: Deploy plugin to ~/.hermes/plugins/web/pagedistiller/
    local target_plugins_web="$HERMES_HOME/plugins/web"
    local target_plugin_dir="$target_plugins_web/pagedistiller"
    local src_plugin_dir="$SCRIPT_DIR/hermes_plugin/pagedistiller"

    if [ ! -d "$src_plugin_dir" ]; then
        log_error "Plugin source directory not found at $src_plugin_dir"
        exit 1
    fi

    mkdir -p "$target_plugins_web"

    if [ -e "$target_plugin_dir" ] || [ -L "$target_plugin_dir" ]; then
        rm -rf "$target_plugin_dir"
    fi

    if [ "$SYMLINK" = true ]; then
        log_info "Symlinking plugin to $target_plugin_dir..."
        ln -s "$src_plugin_dir" "$target_plugin_dir"
        log_ok "Symlinked plugin directory."
    else
        log_info "Copying plugin to $target_plugin_dir..."
        cp -r "$src_plugin_dir" "$target_plugin_dir"
        log_ok "Copied plugin directory."
    fi

    # Step 3: Enable & configure
    if [ "$SKIP_ENABLE" = false ]; then
        local hermes_bin
        if hermes_bin=$(find_hermes_bin); then
            log_info "Enabling plugin in Hermes..."
            "$hermes_bin" plugins enable web/pagedistiller --no-allow-tool-override
            log_ok "Enabled plugin 'web/pagedistiller'."

            log_info "Configuring Hermes extract backend..."
            "$hermes_bin" config set web.extract_backend pagedistiller
            log_ok "Set web.extract_backend = pagedistiller."
        else
            log_warn "Hermes CLI binary not found in PATH."
            log_warn "Please enable manually:"
            log_warn "  hermes plugins enable web/pagedistiller --no-allow-tool-override"
            log_warn "  hermes config set web.extract_backend pagedistiller"
        fi

        # Step 4: Verification
        log_info "Verifying provider resolution in Hermes..."
        local verify_script="
try:
    from tools.web_tools import _ensure_web_plugins_loaded
    _ensure_web_plugins_loaded()
    from agent.web_search_registry import get_active_extract_provider
    p = get_active_extract_provider()
    if p and p.name == 'pagedistiller':
        print('OK')
    else:
        print('FAIL:' + str(p))
except Exception as e:
    print('ERROR:' + str(e))
"
        local verify_res
        verify_res=$("$hermes_py" -c "$verify_script" 2>/dev/null || echo "EXEC_FAIL")
        if [ "$verify_res" = "OK" ]; then
            log_ok "Verified: PageDistiller is now the active web extract provider!"
        else
            log_warn "Provider check returned: $verify_res"
            log_warn "The plugin is installed and will be active on next Hermes session."
        fi
    else
        log_info "Skipping plugin enable and config (--no-enable was passed)."
    fi

    echo ""
    log_ok "${BOLD}PageDistiller installation successful!${NC}"
    echo "To test standalone extraction:"
    echo "  pagedistiller https://example.com"
    echo ""
    echo "To test via Hermes:"
    echo "  hermes chat -q \"Extract content from https://example.com\""
}

if [ "$UNINSTALL" = true ]; then
    do_uninstall
else
    do_install
fi
