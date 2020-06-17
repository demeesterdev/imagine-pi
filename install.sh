#!/usr/bin/env bash

if [ "$EUID" -ne 0 ]; then
    INVOCATION="$(printf %q "$BASH_SOURCE")"
    echo "Script must be run as root. Try 'sudo bash $INVOCATION'"
    exit
fi

if ![ hash python3 2>/dev/null ]; then
    echo "Python3 not available. Install Python3 first"
    exit
fi

if ![ hash whiptail 2>/dev/null ]; then
    echo "whiptail not available. Install whiptail first"
    exit
fi

echo "installing imagine_py"
{
    cp ./imagine_pi.py /usr/local/bin/imagine_pi
    chmod +x /usr/local/bin/imagine_pi
    echo "installed"
} || {
    ex_code = $?
    echo "$ex_code"
    echo "installation failed"
}



