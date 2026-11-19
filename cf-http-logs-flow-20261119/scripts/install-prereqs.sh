#!/usr/bin/env bash
# Installs what this example needs on macOS (Homebrew), Debian/Ubuntu (apt) or Fedora (dnf). Safe to run again.
# On Windows, run it inside WSL (Ubuntu).
set -uo pipefail

have() { command -v "$1" >/dev/null 2>&1; }

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    echo "This is Windows without WSL. Install WSL with Ubuntu, open an Ubuntu terminal, and run this script there." >&2
    exit 1
    ;;
esac

if have brew; then PM=brew
elif have apt-get; then PM=apt
elif have dnf; then PM=dnf
else
  echo "Found no brew, apt-get or dnf. On a Mac, install Homebrew first (https://brew.sh); otherwise install the tools in the README table by hand." >&2
  exit 1
fi

SUDO=sudo
[ "$(id -u)" = 0 ] && SUDO=""

pkg_install() {
  case "$PM" in
    brew) brew install "$1" ;;
    apt) $SUDO apt-get install -y "$2" ;;
    dnf) $SUDO dnf install -y "$3" ;;
  esac
}

check() {
  if have "$1"; then
    echo "ok        $1"
  else
    echo "installing $1"
    pkg_install "$2" "$3" "$4" || echo "MISSING   $1: install it by hand (see the README table)" >&2
  fi
}

if have make; then
  echo "ok        make"
elif [ "$(uname -s)" = "Darwin" ]; then
  xcode-select --install
else
  check make make make make
fi

check jq jq jq jq

# The AWS CLI v2, for the bucket in step 1. `aws login` needs 2.32 or newer. Homebrew has awscli v2; apt and dnf do not, so Linux
# uses AWS's own installer (needs curl and unzip).
aws_version() { aws --version 2>&1 | sed -n 's|^aws-cli/\([0-9.]*\).*|\1|p'; }
aws_ok() { have aws && [ "$(printf '2.32.0\n%s\n' "$(aws_version)" | sort -V | head -1)" = "2.32.0" ]; }

install_aws_linux() {
  case "$(uname -m)" in
    x86_64) arch=x86_64 ;;
    aarch64|arm64) arch=aarch64 ;;
    *) echo "MISSING   aws: no installer for $(uname -m); see https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html" >&2; return 1 ;;
  esac
  have curl || pkg_install curl curl curl
  have unzip || pkg_install unzip unzip unzip
  tmp=$(mktemp -d)
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-$arch.zip" -o "$tmp/awscliv2.zip" \
    && unzip -q "$tmp/awscliv2.zip" -d "$tmp" \
    && $SUDO "$tmp/aws/install" --update
  status=$?
  rm -rf "$tmp"
  return $status
}

if aws_ok; then
  echo "ok        aws $(aws_version)"
else
  echo "installing aws (v2.32 or newer)"
  if [ "$PM" = "brew" ]; then
    { brew install awscli || brew upgrade awscli; } || echo "MISSING   aws: install it by hand (see the README table)" >&2
  else
    install_aws_linux || echo "MISSING   aws: install it by hand (see the README table)" >&2
  fi
  aws_ok || echo "MISSING   aws 2.32 or newer: 'aws --version' prints '$(have aws && aws_version || echo none)'" >&2
fi

if have go; then
  echo "ok        go $(go version | awk '{print $3}')"
else
  check go go golang-go golang
  echo "NOTE      the CLI needs Go 1.27 or newer; an older Go that supports toolchain switching downloads it by itself"
fi

if python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
  echo "ok        python3 $(python3 -c 'import sys; print(sys.version.split()[0])')"
elif [ "$PM" = "brew" ]; then
  brew install python@3.13
  echo "NOTE      open a new terminal, then check that 'python3 --version' prints 3.11 or newer"
else
  echo "MISSING   python3 3.11 or newer: install it from python.org, or with 'uv python install 3.13'" >&2
fi

if have aws && ! aws sts get-caller-identity --cli-connect-timeout 5 --cli-read-timeout 5 >/dev/null 2>&1; then
  echo "NOTE      the AWS CLI is not signed in. Run 'aws login --region <bucket region>' (opens a browser), or 'aws configure sso' / 'aws configure' (see the README)"
fi
