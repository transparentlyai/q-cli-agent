"""
Command analyzer for shell command safety verification.
Parses shell commands to identify potentially dangerous operations
regardless of how they're invoked (directly, via pipes, xargs, etc.)
"""

import re
import shlex
import logging
import os
from pathlib import Path
from typing import Dict, List, Tuple, Any

from q.core.logging import get_logger

logger = get_logger(__name__)

# Dangerous command patterns - both the commands themselves and common flags
DANGEROUS_COMMANDS = {
    # File deletion/modification - rm is handled specially
    "shred": {"severity": "high", "description": "Secure file deletion"},
    "srm": {"severity": "high", "description": "Secure file deletion"},
    "wipe": {"severity": "high", "description": "Secure file deletion"},
    
    # System modification
    "mkfs": {"severity": "critical", "description": "Filesystem creation"},
    "dd": {"severity": "critical", "description": "Low-level data operations"},
    "fdisk": {"severity": "critical", "description": "Disk partitioning"},
    "parted": {"severity": "critical", "description": "Disk partitioning"},
    "chmod": {"severity": "medium", "description": "Change file permissions"},
    "chown": {"severity": "medium", "description": "Change file ownership"},
    
    # Privilege escalation
    "sudo": {"severity": "high", "description": "Privilege escalation"},
    "su": {"severity": "high", "description": "User switching"},
    "doas": {"severity": "high", "description": "Privilege escalation"},
    
    # Network/remote execution
    "curl": {"severity": "medium", "description": "Download content"},
    "wget": {"severity": "medium", "description": "Download content"},
}

# Commands that need context-aware analysis
CONTEXT_AWARE_COMMANDS = {
    "rm": {"severity": "medium", "description": "File deletion"},
}

# Dangerous flag patterns
DANGEROUS_FLAGS = {
    "rm": ["-rf", "-fr", "--force", "--recursive", "--no-preserve-root"],
    "chmod": ["777", "a+rwx", "o+w"],
    "curl": ["-o", "--output", "| sh", "| bash"],
    "wget": ["-O", "--output-document", "| sh", "| bash"],
}

# Commands that can execute other commands
EXECUTION_COMMANDS = {
    "xargs": {"severity": "medium", "description": "Execute commands from input"},
    "eval": {"severity": "high", "description": "Execute string as command"},
    "exec": {"severity": "high", "description": "Replace current process with command"},
    "bash": {"severity": "medium", "description": "Execute bash script/command"},
    "sh": {"severity": "medium", "description": "Execute shell script/command"},
    "source": {"severity": "medium", "description": "Execute commands from file"},
    ".": {"severity": "medium", "description": "Execute commands from file"},
}

# Dangerous path patterns
DANGEROUS_PATHS = [
    "/",
    "/*",
    "/etc",
    "/etc/*",
    "/var",
    "/var/*",
    "/usr",
    "/usr/*",
    "/bin",
    "/bin/*",
    "/sbin",
    "/sbin/*",
    "/boot",
    "/boot/*",
    "/dev",
    "/dev/*",
    "/proc",
    "/proc/*",
    "/sys",
    "/sys/*",
    "~/.ssh",
    "~/.ssh/*",
]


def tokenize_command(command_str: str) -> List[List[str]]:
    """
    Tokenize a shell command into its components, handling pipes and redirections.
    
    Args:
        command_str: The shell command string
        
    Returns:
        A list of command segments, where each segment is a list of tokens
    """
    # Split by pipes first
    pipe_segments = command_str.split("|")
    command_segments = []
    
    for segment in pipe_segments:
        # Handle redirections and split into tokens
        # This is simplified - a full parser would be more complex
        segment = segment.strip()
        
        # Skip empty segments
        if not segment:
            continue
            
        try:
            # Use shlex to properly handle quotes and escapes
            tokens = shlex.split(segment)
            command_segments.append(tokens)
        except Exception as e:
            logger.warning(f"Error tokenizing command segment '{segment}': {e}")
            # If tokenization fails, treat the whole segment as one token
            command_segments.append([segment])
    
    return command_segments


def _severity_level(severity: str) -> int:
    """Convert severity string to numeric level for comparison"""
    levels = {
        'low': 0,
        'medium': 1,
        'high': 2,
        'critical': 3
    }
    return levels.get(severity, 0)


def _is_path_sensitive(path: str) -> bool:
    """
    Check if a path is sensitive.
    
    Args:
        path: The path to check
        
    Returns:
        True if the path is sensitive, False otherwise
    """
    # Skip checking command-line options that start with -
    if path.startswith('-'):
        return False
        
    # Expand ~ to home directory
    if path.startswith('~'):
        path = os.path.expanduser(path)
    
    # Check against dangerous paths
    for sensitive_path in DANGEROUS_PATHS:
        # Expand ~ in sensitive paths too
        if sensitive_path.startswith('~'):
            expanded_sensitive = os.path.expanduser(sensitive_path)
        else:
            expanded_sensitive = sensitive_path
            
        # Direct match
        if path == expanded_sensitive:
            return True
            
        # Check if path is under a sensitive directory
        if expanded_sensitive.endswith('/*'):
            prefix = expanded_sensitive[:-1]  # Remove the *
            if path.startswith(prefix):
                return True
                
        # Check for absolute paths that match sensitive patterns
        if path.startswith('/') and sensitive_path.startswith('/'):
            if path == sensitive_path or path.startswith(sensitive_path + '/'):
                return True
    
    # Check for wildcard usage (which could potentially include sensitive paths)
    if '*' in path:
        return True
        
    return False


def _has_dangerous_flags(cmd: str, args: List[str]) -> bool:
    """Check if command has dangerous flags"""
    if cmd not in DANGEROUS_FLAGS:
        return False
    
    for arg in args:
        if arg in DANGEROUS_FLAGS[cmd]:
            return True
    
    return False


def analyze_command(command_str: str) -> Dict[str, Any]:
    """
    Analyze a shell command for potential dangers.
    
    Args:
        command_str: The shell command string
        
    Returns:
        A dictionary with analysis results:
        {
            'is_dangerous': bool,
            'danger_level': 'low'|'medium'|'high'|'critical',
            'reasons': [list of reasons why command is flagged],
            'command_segments': [parsed command segments]
        }
    """
    result = {
        'is_dangerous': False,
        'danger_level': 'low',
        'reasons': [],
        'command_segments': []
    }
    
    # Tokenize the command
    try:
        command_segments = tokenize_command(command_str)
        result['command_segments'] = command_segments
    except Exception as e:
        logger.error(f"Failed to tokenize command '{command_str}': {e}")
        result['is_dangerous'] = True
        result['danger_level'] = 'medium'
        result['reasons'].append(f"Command parsing failed: {e}")
        return result
    
    # Check for empty command
    if not command_segments:
        return result
        
    # Analyze each command segment
    for i, segment in enumerate(command_segments):
        if not segment:
            continue
            
        cmd = segment[0].lower()
        args = segment[1:] if len(segment) > 1 else []
        
        # Check if this is a dangerous command
        if cmd in DANGEROUS_COMMANDS:
            cmd_info = DANGEROUS_COMMANDS[cmd]
            result['is_dangerous'] = True
            
            # Update danger level if higher
            if _severity_level(cmd_info['severity']) > _severity_level(result['danger_level']):
                result['danger_level'] = cmd_info['severity']
                
            reason = f"Command '{cmd}' ({cmd_info['description']})"
            result['reasons'].append(reason)
            
            # Check for dangerous flags
            if cmd in DANGEROUS_FLAGS:
                for arg in args:
                    if arg in DANGEROUS_FLAGS[cmd]:
                        result['reasons'].append(f"Dangerous flag '{arg}' used with '{cmd}'")
                        # Increase severity for dangerous flags
                        if result['danger_level'] != 'critical':
                            result['danger_level'] = 'high'
            
            # Check for dangerous paths
            sensitive_paths = []
            for arg in args:
                if _is_path_sensitive(arg):
                    sensitive_paths.append(arg)
                    
            if sensitive_paths:
                result['reasons'].append(f"Operation on sensitive paths: {', '.join(sensitive_paths)}")
                if result['danger_level'] != 'critical':
                    result['danger_level'] = 'high'
        
        # Special handling for context-aware commands like rm
        elif cmd in CONTEXT_AWARE_COMMANDS:
            cmd_info = CONTEXT_AWARE_COMMANDS[cmd]
            
            # For rm, only flag as dangerous if:
            # 1. It has dangerous flags (-rf, etc.)
            # 2. It targets sensitive paths
            # 3. It's used with wildcards (*)
            
            has_dangerous_flags = _has_dangerous_flags(cmd, args)
            
            # Check for sensitive paths
            sensitive_paths = []
            for arg in args:
                if _is_path_sensitive(arg):
                    sensitive_paths.append(arg)
            
            has_sensitive_paths = len(sensitive_paths) > 0
            has_wildcards = any('*' in arg for arg in args)
            
            if has_dangerous_flags or has_sensitive_paths or has_wildcards:
                result['is_dangerous'] = True
                
                # Set severity based on context
                if has_sensitive_paths:
                    result['danger_level'] = 'high'
                    result['reasons'].append(f"Command '{cmd}' targeting sensitive paths: {', '.join(sensitive_paths)}")
                elif has_dangerous_flags:
                    result['danger_level'] = 'high'
                    for arg in args:
                        if cmd in DANGEROUS_FLAGS and arg in DANGEROUS_FLAGS[cmd]:
                            result['reasons'].append(f"Dangerous flag '{arg}' used with '{cmd}'")
                elif has_wildcards:
                    result['danger_level'] = 'medium'
                    result['reasons'].append(f"Command '{cmd}' with wildcards")
            
        # Check if this is a command execution wrapper
        if cmd in EXECUTION_COMMANDS:
            cmd_info = EXECUTION_COMMANDS[cmd]
            
            # For xargs and similar, we need to check what command it's executing
            if cmd == 'xargs' and args:
                # xargs can have the command as the first argument or after flags
                potential_cmd = None
                for arg in args:
                    if not arg.startswith('-'):
                        potential_cmd = arg.lower()
                        break
                
                if potential_cmd in DANGEROUS_COMMANDS:
                    subcmd_info = DANGEROUS_COMMANDS[potential_cmd]
                    result['is_dangerous'] = True
                    
                    # Update danger level if higher
                    if _severity_level(subcmd_info['severity']) > _severity_level(result['danger_level']):
                        result['danger_level'] = subcmd_info['severity']
                        
                    reason = f"Dangerous command '{potential_cmd}' executed via {cmd}"
                    result['reasons'].append(reason)
                
                # Also check context-aware commands
                elif potential_cmd in CONTEXT_AWARE_COMMANDS:
                    # For rm via xargs, be more cautious since we can't easily check the targets
                    result['is_dangerous'] = True
                    result['danger_level'] = 'medium'
                    result['reasons'].append(f"Command '{potential_cmd}' executed via {cmd}")
            
            # For eval, exec, bash, etc. - check the arguments for dangerous patterns
            else:
                # Join args to check for shell syntax
                args_str = ' '.join(args)
                for dangerous_cmd in DANGEROUS_COMMANDS:
                    if dangerous_cmd in args_str:
                        cmd_info = DANGEROUS_COMMANDS[dangerous_cmd]
                        result['is_dangerous'] = True
                        
                        # Update danger level if higher
                        if _severity_level(cmd_info['severity']) > _severity_level(result['danger_level']):
                            result['danger_level'] = cmd_info['severity']
                            
                        reason = f"Dangerous command '{dangerous_cmd}' potentially executed via {cmd}"
                        result['reasons'].append(reason)
                
                # Also check context-aware commands
                for context_cmd in CONTEXT_AWARE_COMMANDS:
                    if context_cmd in args_str:
                        result['is_dangerous'] = True
                        result['danger_level'] = 'medium'
                        reason = f"Command '{context_cmd}' potentially executed via {cmd}"
                        result['reasons'].append(reason)
        
        # Special case for pipe chains
        if i > 0 and cmd == 'xargs':
            # Check if xargs is being used without explicit command (uses rm by default)
            if not args or all(arg.startswith('-') for arg in args):
                for dangerous_cmd in ['rm']:  # Could expand this list
                    result['is_dangerous'] = True
                    result['danger_level'] = 'medium'  # Lower severity for implicit rm
                    reason = f"Command '{dangerous_cmd}' may be implicitly used with xargs"
                    result['reasons'].append(reason)
    
    # Check for shell script execution via pipe
    if "|" in command_str and ("sh" in command_str or "bash" in command_str):
        if re.search(r'\|\s*(ba)?sh', command_str):
            result['is_dangerous'] = True
            if _severity_level('high') > _severity_level(result['danger_level']):
                result['danger_level'] = 'high'
            result['reasons'].append("Piping content directly to shell for execution")
    
    return result


def is_command_safe(command_str: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Determine if a command is safe to execute.
    
    Args:
        command_str: The shell command string
        
    Returns:
        (is_safe, analysis_result) tuple
    """
    analysis = analyze_command(command_str)
    return not analysis['is_dangerous'], analysis