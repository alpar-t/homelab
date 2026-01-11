#!/bin/bash
#
# Immich Bulk Upload Script
# 
# Efficiently uploads a large media collection to Immich with:
# - Progress tracking at month-folder granularity (year/month)
# - Per-folder error handling with retries
# - Resumability - only marks complete AFTER successful upload
# - Detailed logging
#
# Usage: ./immich-bulk-upload.sh /path/to/media/collection
#

set -uo pipefail

# ============================================================================
# Configuration
# ============================================================================

# Immich server (use LAN address to bypass Cloudflare 100MB limit)
IMMICH_SERVER="${IMMICH_SERVER:-http://192.168.1.203:2283}"

# Number of concurrent uploads
# Default: 4 - good balance for gigabit network and 3-node Odroid cluster
# - Single HDD source: use 2 (avoids seek thrashing)
# - RAID array / SSD source: use 4-6 (network/server becomes bottleneck)
# - 10GbE network: use 8-12
CONCURRENCY="${CONCURRENCY:-4}"

# Maximum retries per folder
MAX_RETRIES="${MAX_RETRIES:-3}"

# Delay between retries (seconds, will use exponential backoff)
RETRY_DELAY="${RETRY_DELAY:-30}"

# Log directory
LOG_DIR="${LOG_DIR:-$HOME/.immich-upload}"

# Default source directory (Photoprism originals)
DEFAULT_SOURCE="/srv/photoprism/originals"

# ============================================================================
# Setup
# ============================================================================

SCRIPT_NAME=$(basename "$0")
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    local level="$1"
    shift
    local msg="$*"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    case "$level" in
        INFO)  echo -e "${BLUE}[INFO]${NC} $msg" ;;
        OK)    echo -e "${GREEN}[OK]${NC} $msg" ;;
        WARN)  echo -e "${YELLOW}[WARN]${NC} $msg" ;;
        ERROR) echo -e "${RED}[ERROR]${NC} $msg" ;;
    esac
    
    echo "[$timestamp] [$level] $msg" >> "$LOG_FILE"
}

die() {
    log ERROR "$@"
    exit 1
}

# ============================================================================
# Progress Tracking
# ============================================================================

PROGRESS_FILE=""
FAILED_FILE=""

init_progress_tracking() {
    local media_dir="$1"
    local dir_hash
    dir_hash=$(echo -n "$media_dir" | md5sum | cut -d' ' -f1)
    
    mkdir -p "$LOG_DIR"
    
    PROGRESS_FILE="$LOG_DIR/progress_${dir_hash}.txt"
    FAILED_FILE="$LOG_DIR/failed_${dir_hash}.txt"
    LOG_FILE="$LOG_DIR/upload_${TIMESTAMP}.log"
    
    log INFO "Progress file: $PROGRESS_FILE"
    log INFO "Log file: $LOG_FILE"
    
    # Initialize files if they don't exist
    touch "$PROGRESS_FILE"
    : > "$FAILED_FILE"  # Clear failed file on new run
}

is_folder_completed() {
    local folder="$1"
    grep -Fxq "$folder" "$PROGRESS_FILE" 2>/dev/null
}

mark_folder_completed() {
    local folder="$1"
    echo "$folder" >> "$PROGRESS_FILE"
}

mark_folder_failed() {
    local folder="$1"
    local error="$2"
    echo "$folder|$error" >> "$FAILED_FILE"
}

# ============================================================================
# Upload Logic
# ============================================================================

upload_folder() {
    local folder="$1"
    local display_name="$2"
    local attempt=1
    local delay="$RETRY_DELAY"
    
    while [ $attempt -le $MAX_RETRIES ]; do
        log INFO "Uploading '$display_name' (attempt $attempt/$MAX_RETRIES)..."
        
        if immich upload \
            --recursive \
            --concurrency "$CONCURRENCY" \
            "$folder"; then
            
            log OK "Successfully uploaded '$display_name'"
            return 0
        else
            log WARN "Upload of '$display_name' failed"
            
            if [ $attempt -lt $MAX_RETRIES ]; then
                log INFO "Waiting ${delay}s before retry..."
                sleep "$delay"
                delay=$((delay * 2))  # Exponential backoff
            fi
        fi
        
        attempt=$((attempt + 1))
    done
    
    return 1
}

# Get all uploadable folders (year/month structure)
# Returns folders at the deepest consistent level for granular progress tracking
get_upload_folders() {
    local media_dir="$1"
    
    # Iterate through year folders
    for year_dir in "$media_dir"/*/; do
        [ -d "$year_dir" ] || continue
        # Remove trailing slash for clean paths
        year_dir="${year_dir%/}"
        
        # Check if this year folder has month subfolders
        local has_subfolders=false
        for month_dir in "$year_dir"/*/; do
            if [ -d "$month_dir" ]; then
                has_subfolders=true
                # Output month folder (null-separated), remove trailing slash
                printf '%s\0' "${month_dir%/}"
            fi
        done
        
        # If no month subfolders, output the year folder directly
        if [ "$has_subfolders" = false ]; then
            printf '%s\0' "$year_dir"
        fi
    done
}

# Get display name for a folder (year/month format)
get_display_name() {
    local folder="$1"
    local media_dir="$2"
    
    # Get relative path from media_dir
    local rel_path="${folder#$media_dir/}"
    echo "$rel_path"
}

upload_collection() {
    local media_dir="$1"
    
    # Collect all folders to upload
    local folders=()
    while IFS= read -r -d '' folder; do
        folders+=("$folder")
    done < <(get_upload_folders "$media_dir")
    
    local total=${#folders[@]}
    local completed=0
    local skipped=0
    local failed=0
    local succeeded=0
    
    log INFO "Found $total folders to process (year/month granularity)"
    
    # Count already completed
    for folder in "${folders[@]}"; do
        if is_folder_completed "$folder"; then
            skipped=$((skipped + 1))
        fi
    done
    
    if [ $skipped -gt 0 ]; then
        log INFO "Resuming: $skipped folders already completed"
    fi
    
    echo ""
    echo "=========================================="
    echo "  Starting Immich Bulk Upload"
    echo "  Source: $media_dir"
    echo "  Folders: $total total, $skipped already done"
    echo "  Concurrency: $CONCURRENCY"
    echo "=========================================="
    echo ""
    
    for folder in "${folders[@]}"; do
        local display_name
        display_name=$(get_display_name "$folder" "$media_dir")
        
        ((completed++)) || true
        
        # Skip if already completed
        if is_folder_completed "$folder"; then
            log INFO "[$completed/$total] Skipping '$display_name' (already completed)"
            continue
        fi
        
        echo ""
        log INFO "[$completed/$total] Processing '$display_name'..."
        
        if upload_folder "$folder" "$display_name"; then
            # Only mark complete AFTER successful upload
            mark_folder_completed "$folder"
            ((succeeded++)) || true
        else
            ((failed++)) || true
            mark_folder_failed "$folder" "Max retries exceeded"
            log ERROR "Failed to upload '$display_name' after $MAX_RETRIES attempts"
            
            # Ask whether to continue or abort
            echo ""
            read -rp "Continue with remaining folders? [Y/n] " continue_choice
            if [[ "$continue_choice" =~ ^[Nn] ]]; then
                log INFO "Upload aborted by user"
                break
            fi
        fi
    done
    
    echo ""
    echo "=========================================="
    echo "  Upload Complete"
    echo "  Total: $total folders"
    echo "  Successful (this run): $succeeded"
    echo "  Skipped (already done): $skipped"  
    echo "  Failed: $failed"
    echo "=========================================="
    
    if [ $failed -gt 0 ]; then
        echo ""
        log WARN "Failed folders saved to: $FAILED_FILE"
        echo "To retry failed folders:"
        echo "  cat '$FAILED_FILE' | cut -d'|' -f1 | while read f; do"
        echo "    immich upload --recursive --concurrency $CONCURRENCY \"\$f\""
        echo "  done"
    fi
    
    echo ""
    log INFO "Full log saved to: $LOG_FILE"
}

# ============================================================================
# Utility Commands  
# ============================================================================

show_status() {
    local media_dir="$1"
    init_progress_tracking "$media_dir"
    
    echo ""
    echo "Upload Status for: $media_dir"
    echo "================================"
    
    local total=0
    local completed=0
    local current_year=""
    
    while IFS= read -r -d '' folder; do
        total=$((total + 1))
        local display_name
        display_name=$(get_display_name "$folder" "$media_dir")
        
        # Extract year for grouping
        local year="${display_name%%/*}"
        if [ "$year" != "$current_year" ]; then
            [ -n "$current_year" ] && echo ""
            echo "  $year/"
            current_year="$year"
        fi
        
        # Get month part if exists
        local month_part=""
        if [[ "$display_name" == */* ]]; then
            month_part="    ${display_name#*/}"
        fi
        
        if is_folder_completed "$folder"; then
            completed=$((completed + 1))
            if [ -n "$month_part" ]; then
                echo -e "  ${GREEN}✓${NC}$month_part"
            else
                echo -e "  ${GREEN}✓${NC} (no subfolders)"
            fi
        else
            if [ -n "$month_part" ]; then
                echo -e "  ${YELLOW}○${NC}$month_part"
            else
                echo -e "  ${YELLOW}○${NC} (no subfolders)"
            fi
        fi
    done < <(get_upload_folders "$media_dir")
    
    echo ""
    echo "Progress: $completed / $total folders completed"
    
    if [ -f "$FAILED_FILE" ] && [ -s "$FAILED_FILE" ]; then
        echo ""
        echo "Failed folders:"
        while IFS='|' read -r folder error; do
            local display_name
            display_name=$(get_display_name "$folder" "$media_dir")
            echo -e "  ${RED}✗${NC} $display_name: $error"
        done < "$FAILED_FILE"
    fi
}

reset_progress() {
    local media_dir="$1"
    init_progress_tracking "$media_dir"
    
    read -rp "Reset all progress for $media_dir? [y/N] " confirm
    if [[ "$confirm" =~ ^[Yy] ]]; then
        rm -f "$PROGRESS_FILE" "$FAILED_FILE"
        log OK "Progress reset"
    fi
}

# ============================================================================
# Main
# ============================================================================

usage() {
    cat << EOF
Usage: $SCRIPT_NAME [OPTIONS] [media-directory]

Efficiently upload a large media collection to Immich.

Commands:
  [directory]          Upload all subfolders (default: $DEFAULT_SOURCE)
  status [directory]   Show upload progress status
  reset [directory]    Reset progress tracking (start fresh)

Options:
  -c, --concurrency N  Number of concurrent uploads (default: $CONCURRENCY)
                       Single HDD: 2 | RAID/SSD: 4-6 | 10GbE: 8-12
  -s, --server URL     Immich server URL (default: $IMMICH_SERVER)
  -r, --retries N      Max retries per folder (default: $MAX_RETRIES)
  -h, --help           Show this help

Environment Variables:
  IMMICH_SERVER        Server URL (overrides default)
  CONCURRENCY          Number of concurrent uploads
  MAX_RETRIES          Maximum retry attempts per folder
  LOG_DIR              Directory for logs and progress (default: ~/.immich-upload)

Progress Tracking:
  - Tracks at year/month granularity for fine-grained resumability
  - Only marks folders complete AFTER successful upload
  - Progress stored in: ~/.immich-upload/

Examples:
  # Upload from default location ($DEFAULT_SOURCE)
  $SCRIPT_NAME

  # Upload from custom location
  $SCRIPT_NAME /mnt/media/photos

  # Lower concurrency for single HDD source
  $SCRIPT_NAME -c 2

  # Higher concurrency for fast source + 10GbE
  $SCRIPT_NAME -c 10

  # Check progress
  $SCRIPT_NAME status

  # Reset and start fresh
  $SCRIPT_NAME reset

EOF
}

main() {
    local cmd=""
    local media_dir=""
    
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -c|--concurrency)
                CONCURRENCY="$2"
                shift 2
                ;;
            -s|--server)
                IMMICH_SERVER="$2"
                shift 2
                ;;
            -r|--retries)
                MAX_RETRIES="$2"
                shift 2
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            status|reset)
                cmd="$1"
                shift
                ;;
            -*)
                die "Unknown option: $1"
                ;;
            *)
                media_dir="$1"
                shift
                ;;
        esac
    done
    
    # Use default source if not specified
    if [ -z "$media_dir" ]; then
        if [ -d "$DEFAULT_SOURCE" ]; then
            media_dir="$DEFAULT_SOURCE"
            echo -e "${BLUE}[INFO]${NC} Using default source: $media_dir"
        else
            usage
            exit 1
        fi
    fi
    
    if [ ! -d "$media_dir" ]; then
        die "Directory not found: $media_dir"
    fi
    
    # Resolve to absolute path
    media_dir=$(cd "$media_dir" && pwd)
    
    # Execute command
    case "$cmd" in
        status)
            show_status "$media_dir"
            ;;
        reset)
            reset_progress "$media_dir"
            ;;
        *)
            init_progress_tracking "$media_dir"
            upload_collection "$media_dir"
            ;;
    esac
}

main "$@"
