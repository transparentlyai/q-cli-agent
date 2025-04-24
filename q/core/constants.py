"""Constants used throughout the application."""

import os

# default MARKER !!DO NOT TOUCH!!
OPERATION_MARKER = "OPERATION"

# Default number of conversation turns to save for session recovery
DEFAULT_SESSION_TURNS = 10

# Paths
HOME_DIR = os.path.expanduser("~")
Q_DIR = os.path.join(HOME_DIR, ".q")
Q_CONFIG_FILE = os.path.join(Q_DIR, "config.py")
Q_HISTORY_FILE = os.path.join(Q_DIR, "history.json")
Q_CONTEXT_FILE = os.path.join(Q_DIR, "context.json")

# Default provider
DEFAULT_PROVIDER = "anthropic"

# Default model
DEFAULT_MODEL = "claude-3-7-sonnet-latest"

# Provider-specific defaults
OPENAI_DEFAULT_MODEL = "gpt-4"
OPENAI_DEFAULT_TEMPERATURE = 0.1
OPENAI_DEFAULT_MAX_TOKENS = 8192
OPENAI_DEFAULT_TOKENS_PER_MIN = 90000  # Default token rate limit for OpenAI

ANTHROPIC_DEFAULT_MODEL = "claude-3-7-sonnet-latest"
ANTHROPIC_DEFAULT_TEMPERATURE = 0.1
ANTHROPIC_DEFAULT_MAX_TOKENS = 8192
ANTHROPIC_DEFAULT_TOKENS_PER_MIN = 100000  # Default token rate limit for Anthropic

VERTEXAI_DEFAULT_MODEL = "gemini-2.0-flash"
VERTEXAI_DEFAULT_LOCATION = "us-central1"
VERTEXAI_DEFAULT_TEMPERATURE = 0.1
VERTEXAI_DEFAULT_MAX_TOKENS = 8192
VERTEXAI_DEFAULT_TOKENS_PER_MIN = 60000  # Default token rate limit for VertexAI

GROQ_DEFAULT_MODEL = "llama3-70b-8192"
GROQ_DEFAULT_TEMPERATURE = 0.1
GROQ_DEFAULT_MAX_TOKENS = 8192
GROQ_DEFAULT_TOKENS_PER_MIN = 200000  # Default token rate limit for Groq

# General LLM defaults
DEFAULT_TEMPERATURE = 0.1
DEFAULT_MAX_TOKENS = 8192
DEFAULT_SYSTEM_PROMPT = ""
DEFAULT_TOKENS_PER_MIN = 90000  # Default general token rate limit

# Retry settings for LLM calls
LLM_RETRY_ATTEMPTS = 5
LLM_RETRY_INITIAL_DELAY = 2
LLM_RETRY_BACKOFF_FACTOR = 2
LLM_RETRY_JITTER_MIN = 0.1
LLM_RETRY_JITTER_MAX = 0.5

# LiteLLM retry settings
LITELLM_NUM_RETRIES = 5
LITELLM_RETRY_AFTER = 30

# Default system prompt
DEFAULT_SYSTEM_PROMPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "prompts",
    "system-prompt.md",
)

# Shell results prompt
SHELL_RESULTS_PROMPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "prompts",
    "shell-results.md",
)

# Import logging constants

# UI colors
OPEARION_SPINNER_MESSAGE_COLOR = "#9B870C"
OPEARION_SPINNER_COMMAND_COLOR = "purple"

# Console padding settings
CONSOLE_LEFT_PADDING = 1
CONSOLE_RIGHT_PADDING = 1

DEFAULT_PROHIBITED_COMMANDS = [
    "sudo *",  # General privilege escalation
    "su *",  # General privilege escalation
    "chmod 777 *",  # Excessive permissions
    "chmod -R 777 *",  # Recursive excessive permissions
    "rm -rf /*",  # Deleting root filesystem
    "dd if=/dev/zero of=/dev/*",  # Overwriting block devices
    "> /dev/sda",  # Overwriting specific block device (example)
    "mkfs.*",  # Formatting filesystems
    ":(){:|:&};:",  # Fork bomb (resource exhaustion)
    "mv /* /dev/null",  # Moving root filesystem contents to null
    "wget * | bash",  # Downloading and executing scripts
    "curl * | bash",  # Downloading and executing scripts
    "wget * | sh",  # Downloading and executing scripts
    "curl * | sh",  # Downloading and executing scripts
    "*(){ :;};*",  # Shellshock vulnerability pattern
    "echo * > /etc/passwd",  # Overwriting password file
    "echo * > /etc/shadow",  # Overwriting shadow password file
    "rm -rf ~",  # Deleting user's home directory
    "rm -rf .",  # Deleting current directory (dangerous if in critical path)
    "find / -delete",  # Find and delete everything from root
    "find . -delete",  # Find and delete everything from current dir
    "shred * /dev/*",  # Securely wiping block devices
    "wipe /dev/*",  # Wiping block devices
    "fdisk /dev/*",  # Disk partitioning tool (interactive)
    "parted /dev/*",  # Disk partitioning tool (interactive/scriptable)
    "gparted /dev/*",  # GUI Disk partitioning tool (can be scripted)
    "userdel root",  # Attempting to delete root user
    "groupdel root",  # Attempting to delete root group
    "passwd -d root",  # Removing root password (security risk)
    "passwd -l root",  # Locking root account
    "chown root* /*",  # Changing ownership of root files (potential breakage)
    "chown -R * /*",  # Recursively changing ownership from root
    "chattr -i *",  # Removing immutable flag (could allow modification of protected files)
    "chattr +i /*",  # Making critical files immutable (could break updates/recovery)
    "reboot",  # System reboot
    "shutdown *",  # System shutdown/reboot/halt
    "halt",  # Halting the system
    "poweroff",  # Powering off the system
    "init 0",  # Halting the system (runlevel)
    "init 6",  # Rebooting the system (runlevel)
    "iptables -F",  # Flushing all firewall rules
    "iptables -X",  # Deleting all non-default firewall chains
    "iptables -P INPUT DROP",  # Setting default input policy to DROP (can lock out)
    "iptables -P FORWARD DROP",  # Setting default forward policy to DROP
    "iptables -P OUTPUT DROP",  # Setting default output policy to DROP (can break connectivity)
    "ufw disable",  # Disabling Uncomplicated Firewall
    "systemctl stop firewalld",  # Stopping firewalld service
    "systemctl disable firewalld",  # Disabling firewalld service
    "insmod *",  # Inserting kernel modules
    "rmmod *",  # Removing kernel modules
    "modprobe *",  # Kernel module management (loading/unloading)
    "sysctl *",  # Modifying kernel parameters at runtime
    "echo * > /proc/sys/*",  # Writing directly to kernel parameters
    "* | base64 -d | bash",  # Pattern for executing base64 encoded scripts
    "* | base64 -d | sh",  # Pattern for executing base64 encoded scripts
    "history -c",  # Clearing command history
    "echo > ~/.bash_history",  # Clearing bash history file
    "kill -9 1",  # Attempting to kill init process (PID 1)
    "pkill init",  # Attempting to kill init process by name
    "mount -o remount,ro /",  # Remounting root filesystem as read-only (can cause issues)
    "mount /dev/sd* /mnt; rm -rf /mnt/*",  # Mounting and deleting files
]

DEFAULT_APPROVED_COMMANDS = [
    # Basic commands without arguments
    "ls",  # List directory contents (no args)
    "ls *",  # List directory contents (with args)
    "cd",  # Change to home directory (no args)
    "cd *",  # Change directory (with args)
    "pwd",  # Print working directory
    "echo",  # Display empty line (no args)
    "echo *",  # Display text (with args)
    "cat",  # Wait for stdin (no args)
    "cat *",  # Concatenate and display files
    "head",  # Wait for stdin (no args)
    "head *",  # Display first part of files
    "tail",  # Wait for stdin (no args)
    "tail *",  # Display last part of files
    "grep",  # Wait for stdin (no args)
    "grep *",  # Search text using patterns
    "find",  # Find in current directory (no args)
    "find *",  # Search for files
    "mkdir",  # Error but harmless (no args)
    "mkdir *",  # Create directories
    "touch",  # Error but harmless (no args)
    "touch *",  # Change file timestamps / create empty files
    "cp",  # Error but harmless (no args)
    "cp *",  # Copy files and directories
    "mv",  # Error but harmless (no args)
    "mv *",  # Move/rename files and directories
    "python --version",  # Check Python version
    "python -m *",  # Run Python module
    "python3 --version",  # Check Python 3 version
    "python3 -m *",  # Run Python 3 module
    "pip list",  # List installed Python packages
    "pip show *",  # Show details about Python packages
    "pip freeze",  # Output installed packages in requirements format
    "uv list",  # List installed Python packages (using uv)
    "uv pip list",  # List installed Python packages (using uv)
    "uv pip show *",  # Show details about Python packages (using uv)
    "uv pip freeze",  # Output installed packages (using uv)
    "cloc",  # Count lines of code (current dir)
    "cloc *",  # Count lines of code
    "git",  # Show git help (no args)
    "git *",  # Git version control commands
    "date",  # Display current date and time
    "cal",  # Display calendar
    "uptime",  # Show how long system has been running
    "whoami",  # Display current user ID
    "id",  # Display user and group IDs
    "uname",  # Print system information (no args)
    "uname *",  # Print system information
    "df",  # Report file system disk space usage (no args)
    "df *",  # Report file system disk space usage
    "du",  # Estimate file space usage (current dir)
    "du *",  # Estimate file space usage
    "wc",  # Wait for stdin (no args)
    "wc *",  # Print newline, word, and byte counts for files
    "less",  # Wait for stdin (no args)
    "less *",  # Pager for viewing files (interactive)
    "more",  # Wait for stdin (no args)
    "more *",  # Pager for viewing files (interactive)
    "diff",  # Error but harmless (no args)
    "diff *",  # Compare files line by line
    "comm",  # Error but harmless (no args)
    "comm *",  # Compare two sorted files line by line
    "sort",  # Wait for stdin (no args)
    "sort *",  # Sort lines of text files
    "uniq",  # Wait for stdin (no args)
    "uniq *",  # Report or omit repeated lines
    "ps",  # Report process status (no args)
    "ps *",  # Report process status
    "top",  # Display system processes (interactive)
    "env",  # Display environment variables
    "printenv",  # Print all environment variables (no args)
    "printenv *",  # Print environment variables
    "export -p",  # List exported environment variables
    "man",  # Error but harmless (no args)
    "man *",  # Display manual pages
    "info",  # Show info directory (no args)
    "info *",  # Display command information (GNU)
    "tldr",  # Show tldr pages index (no args)
    "tldr *",  # Simplified man pages
    "* --help",  # Common pattern for command help
    "stat",  # Error but harmless (no args)
    "stat *",  # Display file or file system status
    "which",  # Error but harmless (no args)
    "which *",  # Locate a command
    "whereis",  # Error but harmless (no args)
    "whereis *",  # Locate binary, source, and manual page for command
    "type",  # Error but harmless (no args)
    "type *",  # Describe how a command name would be interpreted
    "history",  # Display command history
    "clear",  # Clear the terminal screen
    "ping",  # Error but harmless (no args)
    "ping *",  # Check network connectivity to a host
    "ip",  # Show IP commands (no args)
    "ip *",  # Show / manipulate routing, network devices, interfaces (read-only use like 'ip addr')
    "ifconfig",  # Show network interfaces (no args)
    "ifconfig *",  # Configure network interfaces (often used read-only)
    "netstat",  # Print network connections (no args)
    "netstat *",  # Print network connections, routing tables, interface stats (read-only options often safe)
    "ss",  # Display socket statistics (no args)
    "ss *",  # Socket statistics (modern replacement for netstat, read-only options safe)
    "host",  # Error but harmless (no args)
    "host *",  # DNS lookup utility
    "dig",  # Show dig help (no args)
    "dig *",  # DNS lookup utility (more detailed)
    "nslookup",  # Interactive mode (no args)
    "nslookup *",  # DNS lookup utility (interactive/non-interactive)
    "tar -tvf *",  # List contents of a tar archive
    "zipinfo *",  # List detailed information about a ZIP archive
    "unzip -l *",  # List contents of a ZIP archive
    "gzip -l *",  # Display compression statistics for gzip files
    "gunzip -l *",  # Display compression statistics for gzip files (same as gzip -l)
    "zcat *",  # Display contents of gzipped files
    "bzcat *",  # Display contents of bzip2 compressed files
    "xzcat *",  # Display contents of xz compressed files
    "basename *",  # Strip directory and suffix from filenames
    "dirname *",  # Strip last component from file name
    "readlink *",  # Read value of a symbolic link
    "test *",  # Check file types and compare values (shell builtin)
    "[ * ]",  # Alternate syntax for 'test' (shell builtin)
    "alias",  # List defined aliases
    "jobs",  # List active jobs
    "file",  # Error but harmless (no args)
    "file *",  # Determine file type
]

# File approvals
DEFAULT_RESTRICTED_PATHS = [
    # Core System & Configuration
    "/",  # Root directory itself (access often needed, modification restricted)
    "/etc/*",  # System-wide configuration files
    "/boot/*",  # Bootloader files, kernel images
    "/root/*",  # Home directory of the root user
    "/sbin/*",  # Essential system binaries (usually admin-only execution)
    "/usr/sbin/*",  # Non-essential system binaries (usually admin-only execution)
    "/usr/local/sbin/*",  # Local system binaries (usually admin-only execution)
    "/var/log/*",  # System logs (often read-only for users, write-restricted)
    "/var/spool/*",  # System spool directories (mail, cron, print jobs)
    "/var/lib/*",  # System state information (databases, package manager data)
    "/var/run/*",  # Runtime variable data (often symlinked to /run)
    "/run/*",  # Runtime variable data
    # Libraries & Binaries (Modification restriction)
    "/bin/*",  # Essential user binaries
    "/lib/*",  # Essential shared libraries
    "/lib64/*",  # Essential 64-bit shared libraries
    "/usr/bin/*",  # Non-essential user binaries
    "/usr/lib/*",  # Non-essential shared libraries
    "/usr/lib64/*",  # Non-essential 64-bit shared libraries
    "/usr/include/*",  # Standard C include files
    "/usr/local/bin/*",  # Local binaries (often admin-managed)
    "/usr/local/lib/*",  # Local libraries (often admin-managed)
    "/usr/local/include/*",  # Local include files (often admin-managed)
    "/opt/*",  # Optional application software packages (often admin-managed)
    # Devices & Kernel Interfaces
    "/dev/*",  # Device files (highly sensitive)
    "/proc/*",  # Process information virtual filesystem (read-only generally okay, write dangerous)
    "/sys/*",  # System/kernel information virtual filesystem (read-only generally okay, write dangerous)
    # Specific Sensitive Files & Directories
    "/etc/passwd",  # User account information
    "/etc/shadow",  # Encrypted password information
    "/etc/gshadow",  # Encrypted group password information
    "/etc/group",  # Group information
    "/etc/sudoers",  # Sudoers configuration
    "/etc/sudoers.d/*",  # Sudoers configuration directory
    "/etc/ssh/*",  # SSH server configuration
    "/etc/fstab",  # Filesystem table
    "/etc/crontab",  # System-wide cron table
    "/etc/cron.*/*",  # System cron job directories
    "/etc/modprobe.d/*",  # Kernel module configuration
    "/etc/sysctl.conf",  # Kernel parameters
    "/etc/sysctl.d/*",  # Kernel parameter configuration directory
    "/lost+found/*",  # Recovered filesystem fragments
]

DEFAULT_ALWAYS_APPROVED_FILE_PATTERNS = [
    "*.c",  # C source
    "*.cpp",  # C++ source
    "*.cs",  # C# source
    "*.css",  # Cascading Style Sheets
    "*.dart",  # Dart source
    "*.go",  # Go source
    "*.h",  # C/C++/Objective-C header
    "*.hpp",  # C++ header
    "*.htm",  # HTML
    "*.html",  # HyperText Markup Language
    "*.java",  # Java source
    "*.js",  # JavaScript
    "*.json",  # Original: JavaScript Object Notation
    "*.jsx",  # JavaScript XML (React)
    "*.kt",  # Kotlin source
    "*.kts",  # Kotlin Script
    "*.md",  # Original: Markdown
    "*.php",  # PHP script
    "*.pl",  # Perl script
    "*.pm",  # Perl module
    "*.ps1",  # PowerShell script
    "*.py",  # Original: Python script
    "*.r",  # R script
    "*.R",  # R script
    "*.rb",  # Ruby script
    "*.rs",  # Rust source
    "*.scala",  # Scala source
    "*.scss",  # Sassy CSS
    "*.sh",  # Shell script
    "*.sql",  # Structured Query Language
    "*.swift",  # Swift source
    "*.ts",  # TypeScript
    "*.tsx",  # TypeScript XML (React)
    "*.txt",  # Original: Text file
    "*.vb",  # Visual Basic source
    "*.xml",  # Extensible Markup Language
    "*.yaml",  # Original: YAML Ain't Markup Language
    "*.yml",  # Original: YAML Ain't Markup Language
]

# Write file approvals
DEFAULT_PROHIBITED_WRITE_PATTERNS = [
    # Core System & Configuration
    "/",  # Root directory itself (access often needed, modification restricted)
    "/etc/*",  # System-wide configuration files
    "/boot/*",  # Bootloader files, kernel images
    "/root/*",  # Home directory of the root user
    "/sbin/*",  # Essential system binaries (usually admin-only execution)
    "/usr/sbin/*",  # Non-essential system binaries (usually admin-only execution)
    "/usr/local/sbin/*",  # Local system binaries (usually admin-only execution)
    "/var/log/*",  # System logs (often read-only for users, write-restricted)
    "/var/spool/*",  # System spool directories (mail, cron, print jobs)
    "/var/lib/*",  # System state information (databases, package manager data)
    "/var/run/*",  # Runtime variable data (often symlinked to /run)
    "/run/*",  # Runtime variable data
    # Libraries & Binaries (Modification restriction)
    "/bin/*",  # Essential user binaries
    "/lib/*",  # Essential shared libraries
    "/lib64/*",  # Essential 64-bit shared libraries
    "/usr/bin/*",  # Non-essential user binaries
    "/usr/lib/*",  # Non-essential shared libraries
    "/usr/lib64/*",  # Non-essential 64-bit shared libraries
    "/usr/include/*",  # Standard C include files
    "/usr/local/bin/*",  # Local binaries (often admin-managed)
    "/usr/local/lib/*",  # Local libraries (often admin-managed)
    "/usr/local/include/*",  # Local include files (often admin-managed)
    "/opt/*",  # Optional application software packages (often admin-managed)
    # Devices & Kernel Interfaces
    "/dev/*",  # Device files (highly sensitive)
    "/proc/*",  # Process information virtual filesystem (read-only generally okay, write dangerous)
    "/sys/*",  # System/kernel information virtual filesystem (read-only generally okay, write dangerous)
    # Specific Sensitive Files & Directories
    "/etc/passwd",  # User account information
    "/etc/shadow",  # Encrypted password information
    "/etc/gshadow",  # Encrypted group password information
    "/etc/group",  # Group information
    "/etc/sudoers",  # Sudoers configuration
    "/etc/sudoers.d/*",  # Sudoers configuration directory
    "/etc/ssh/*",  # SSH server configuration
    "/etc/fstab",  # Filesystem table
    "/etc/crontab",  # System-wide cron table
    "/etc/cron.*/*",  # System cron job directories
    "/etc/modprobe.d/*",  # Kernel module configuration
    "/etc/sysctl.conf",  # Kernel parameters
    "/etc/sysctl.d/*",  # Kernel parameter configuration directory
    "/lost+found/*",  # Recovered filesystem fragments
]

DEFAULT_ALWAYS_APPROVED_WRITE_PATTERNS = []

# Maximum file size for read operations (in bytes)
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

MODELS = (
    {
        "provider": "anthropic",
        "model": "claude-3-7-sonnet-latest",
        "description": "Production-ready - 120K tokens CW, Large/slow model - oversubscribed",
    },
    {
        "provider": "vertexai",
        "model": "gemini-2.5-pro-exp-03-25",
        "description": "Experimental - Large/slow model, 1M tokens CW - oversubscribed",
    },
    {
        "provider": "vertexai",
        "model": "gemini-2.5-flash-preview-04-17",
        "description": "Experimental - Small/fast model, 1M tokens CW - oversubscribed",
    },
    {
        "provider": "openai",
        "model": "o4-mini",
        "description": "Not tested - need API keys",
    },
    {
        "provider": "groq",
        "model": "llama3-70b-8192",
        "description": "Not tested - need API keys",
    },
)

