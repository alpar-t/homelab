#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Migrate a healthy two-instance CloudNativePG cluster to local storage.

The live Cluster spec must already use the target StorageClass, required
cross-node anti-affinity, and resizeInUseVolumes=false. The script advances the
migration from live state, so completed stages are safe to run again.

Usage:
  migrate-cnpg-to-local-storage.sh \
    --namespace NAMESPACE \
    --cluster CLUSTER \
    [--stage STAGE] [--execute] [options]

Stages:
  status             Print the inferred migration state
  preflight          Validate policy, health, placement, backups, and storage
  backup-pre         Create/wait for the stable pre-migration backup
  replace-standby    Replace the Longhorn standby with a local standby
  promote            Promote the synchronized local standby
  replace-remaining  Replace the remaining Longhorn standby
  verify             Verify final placement, replication, archiving, and app
  backup-post        Create/wait for the stable post-migration backup
  all                Run every stage in order (default)

Options:
  --source-class CLASS    Source StorageClass (default: longhorn-ssd)
  --target-class CLASS    Target StorageClass (default: local-ssd)
  --argocd-app NAME       Require this Argo CD Application to be Synced/Healthy
  --deployment NAME       Require this application Deployment to be available
  --timeout SECONDS       Wait timeout per transition (default: 1800)
  --context NAME          kubectl context to use
  --execute               Permit backup, promotion, pod, and PVC mutations
  -h, --help              Show this help

Without --execute, mutating stages print a state-derived plan and make no
changes. Preflight, status, and verify are always read-only.

Examples:
  # Review the complete plan
  scripts/migrate-cnpg-to-local-storage.sh \
    --namespace vikunja --cluster vikunja-db --argocd-app vikunja

  # Execute or resume the complete migration
  scripts/migrate-cnpg-to-local-storage.sh \
    --namespace vikunja --cluster vikunja-db --argocd-app vikunja \
    --deployment vikunja --stage all --execute

  # Resume only the promotion stage
  scripts/migrate-cnpg-to-local-storage.sh \
    --namespace vikunja --cluster vikunja-db --stage promote --execute
EOF
}

NAMESPACE=""
CLUSTER=""
STAGE="all"
SOURCE_CLASS="longhorn-ssd"
TARGET_CLASS="local-ssd"
ARGOCD_APP=""
DEPLOYMENT=""
TIMEOUT_SECONDS=1800
KUBE_CONTEXT=""
EXECUTE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace) NAMESPACE="${2:?missing value for --namespace}"; shift 2 ;;
    --cluster) CLUSTER="${2:?missing value for --cluster}"; shift 2 ;;
    --stage) STAGE="${2:?missing value for --stage}"; shift 2 ;;
    --source-class) SOURCE_CLASS="${2:?missing value for --source-class}"; shift 2 ;;
    --target-class) TARGET_CLASS="${2:?missing value for --target-class}"; shift 2 ;;
    --argocd-app) ARGOCD_APP="${2:?missing value for --argocd-app}"; shift 2 ;;
    --deployment) DEPLOYMENT="${2:?missing value for --deployment}"; shift 2 ;;
    --timeout) TIMEOUT_SECONDS="${2:?missing value for --timeout}"; shift 2 ;;
    --context) KUBE_CONTEXT="${2:?missing value for --context}"; shift 2 ;;
    --execute) EXECUTE=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$STAGE" in
  status|preflight|backup-pre|replace-standby|promote|replace-remaining|verify|backup-post|all) ;;
  *) echo "Invalid --stage: $STAGE" >&2; usage >&2; exit 2 ;;
esac

if [[ -z "$NAMESPACE" || -z "$CLUSTER" ]]; then
  echo "--namespace and --cluster are required" >&2
  usage >&2
  exit 2
fi

if ! [[ "$TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
  echo "--timeout must be a positive integer" >&2
  exit 2
fi

for value in "$NAMESPACE" "$CLUSTER" "$SOURCE_CLASS" "$TARGET_CLASS"; do
  if ! [[ "$value" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]]; then
    echo "Unsafe Kubernetes name: $value" >&2
    exit 2
  fi
done

for command in kubectl jq; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Required command not found: $command" >&2
    exit 1
  fi
done

KUBECTL=(kubectl)
if [[ -n "$KUBE_CONTEXT" ]]; then
  KUBECTL+=(--context "$KUBE_CONTEXT")
fi

k() {
  "${KUBECTL[@]}" "$@"
}

log() {
  echo "==> $*"
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

cluster_json() {
  k get cluster.postgresql.cnpg.io "$CLUSTER" -n "$NAMESPACE" -o json
}

pvc_json() {
  k get pvc -n "$NAMESPACE" -l "cnpg.io/cluster=$CLUSTER" -o json
}

pod_json() {
  k get pod -n "$NAMESPACE" -l "cnpg.io/cluster=$CLUSTER" -o json
}

primary_name() {
  cluster_json | jq -r '.status.currentPrimary // empty'
}

class_count() {
  local storage_class="$1"
  pvc_json | jq --arg class "$storage_class" '[.items[] | select(.spec.storageClassName == $class)] | length'
}

pvc_for_class_except() {
  local storage_class="$1"
  local excluded="$2"
  pvc_json | jq -r --arg class "$storage_class" --arg excluded "$excluded" \
    '.items[] | select(.spec.storageClassName == $class and .metadata.name != $excluded) | .metadata.name'
}

node_for_pod() {
  k get pod "$1" -n "$NAMESPACE" -o jsonpath='{.spec.nodeName}'
}

assert_cluster_healthy() {
  local instances ready phase pvc_count pod_count distinct_nodes
  instances="$(cluster_json | jq -r '.spec.instances')"
  ready="$(cluster_json | jq -r '.status.readyInstances // 0')"
  phase="$(cluster_json | jq -r '.status.phase // empty')"
  pvc_count="$(pvc_json | jq '.items | length')"
  pod_count="$(pod_json | jq '[.items[] | select(.status.phase == "Running")] | length')"
  distinct_nodes="$(pod_json | jq '[.items[] | select(.status.phase == "Running") | .spec.nodeName] | unique | length')"

  [[ "$instances" == "2" ]] || die "$CLUSTER must have exactly 2 instances; found $instances"
  [[ "$ready" == "2" ]] || die "$CLUSTER has $ready/2 ready instances"
  [[ "$phase" == "Cluster in healthy state" ]] || die "$CLUSTER phase is: $phase"
  [[ "$pvc_count" == "2" ]] || die "$CLUSTER has $pvc_count PVCs; expected 2"
  [[ "$pod_count" == "2" ]] || die "$CLUSTER has $pod_count running instance pods; expected 2"
  [[ "$distinct_nodes" == "2" ]] || die "$CLUSTER instances are not on two distinct nodes"
}

assert_target_policy() {
  local actual_class resize anti_type anti_enabled topology binding
  actual_class="$(cluster_json | jq -r '.spec.storage.storageClass // empty')"
  resize="$(cluster_json | jq -r '.spec.storage.resizeInUseVolumes')"
  anti_type="$(cluster_json | jq -r '.spec.affinity.podAntiAffinityType // empty')"
  anti_enabled="$(cluster_json | jq -r '.spec.affinity.enablePodAntiAffinity // true')"
  topology="$(cluster_json | jq -r '.spec.affinity.topologyKey // empty')"
  binding="$(k get storageclass "$TARGET_CLASS" -o jsonpath='{.volumeBindingMode}')"

  [[ "$actual_class" == "$TARGET_CLASS" ]] || die "live Cluster spec uses $actual_class, not $TARGET_CLASS"
  [[ "$resize" == "false" ]] || die "live Cluster spec must set resizeInUseVolumes=false"
  [[ "$anti_enabled" == "true" ]] || die "CNPG pod anti-affinity is disabled"
  [[ "$anti_type" == "required" ]] || die "podAntiAffinityType must be required; found $anti_type"
  [[ "$topology" == "kubernetes.io/hostname" ]] || die "anti-affinity topologyKey must be kubernetes.io/hostname"
  [[ "$binding" == "WaitForFirstConsumer" ]] || die "$TARGET_CLASS must use WaitForFirstConsumer; found $binding"
}

assert_archiving() {
  local status
  status="$(cluster_json | jq -r '[.status.conditions[] | select(.type == "ContinuousArchiving")][0].status // "False"')"
  [[ "$status" == "True" ]] || die "continuous WAL archiving is not healthy"
}

assert_argocd() {
  [[ -n "$ARGOCD_APP" ]] || return 0
  local sync health
  sync="$(k get application.argoproj.io "$ARGOCD_APP" -n argocd -o jsonpath='{.status.sync.status}')"
  health="$(k get application.argoproj.io "$ARGOCD_APP" -n argocd -o jsonpath='{.status.health.status}')"
  [[ "$sync" == "Synced" && "$health" == "Healthy" ]] || \
    die "Argo CD $ARGOCD_APP is $sync/$health, expected Synced/Healthy"
}

assert_deployment() {
  [[ -n "$DEPLOYMENT" ]] || return 0
  local desired available
  desired="$(k get deployment "$DEPLOYMENT" -n "$NAMESPACE" -o jsonpath='{.spec.replicas}')"
  available="$(k get deployment "$DEPLOYMENT" -n "$NAMESPACE" -o jsonpath='{.status.availableReplicas}')"
  [[ -n "$available" && "$available" -ge "$desired" ]] || \
    die "Deployment $NAMESPACE/$DEPLOYMENT has $available/$desired available replicas"
}

assert_known_classes() {
  local unknown
  unknown="$(pvc_json | jq -r --arg source "$SOURCE_CLASS" --arg target "$TARGET_CLASS" \
    '.items[] | select(.spec.storageClassName != $source and .spec.storageClassName != $target) | "\(.metadata.name)=\(.spec.storageClassName)"')"
  [[ -z "$unknown" ]] || die "unexpected CNPG PVC StorageClass: $unknown"
}

assert_source_volumes_healthy() {
  local volume robustness state
  while IFS= read -r volume; do
    [[ -n "$volume" ]] || continue
    robustness="$(k get volumes.longhorn.io "$volume" -n longhorn-system -o jsonpath='{.status.robustness}')"
    state="$(k get volumes.longhorn.io "$volume" -n longhorn-system -o jsonpath='{.status.state}')"
    [[ "$robustness" == "healthy" && "$state" == "attached" ]] || \
      die "source Longhorn volume $volume is $state/$robustness"
  done < <(pvc_json | jq -r --arg source "$SOURCE_CLASS" \
    '.items[] | select(.spec.storageClassName == $source) | .spec.volumeName')
}

assert_replication_caught_up() {
  local primary="$1"
  local standby="$2"
  local row state lag
  row="$(k exec -n "$NAMESPACE" "$primary" -c postgres -- \
    psql -U postgres -d postgres -v ON_ERROR_STOP=1 -Atqc \
    "SELECT state || '|' || COALESCE(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)::text, '') FROM pg_stat_replication WHERE application_name = '$standby'")"
  state="${row%%|*}"
  lag="${row#*|}"
  [[ "$state" == "streaming" && "$lag" == "0" ]] || \
    die "replication $primary -> $standby is state=$state lag=$lag bytes"
}

wait_for_state() {
  local expected_source="$1"
  local expected_target="$2"
  local expected_primary_class="$3"
  local deadline=$(( $(date +%s) + TIMEOUT_SECONDS ))
  local source target ready phase primary primary_class

  while (( $(date +%s) < deadline )); do
    source="$(class_count "$SOURCE_CLASS")"
    target="$(class_count "$TARGET_CLASS")"
    ready="$(cluster_json | jq -r '.status.readyInstances // 0')"
    phase="$(cluster_json | jq -r '.status.phase // empty')"
    primary="$(primary_name)"
    primary_class="$(pvc_json | jq -r --arg primary "$primary" '.items[] | select(.metadata.name == $primary) | .spec.storageClassName')"
    log "state: source=$source target=$target ready=$ready phase='$phase' primary=$primary/$primary_class"
    if [[ "$source" == "$expected_source" && "$target" == "$expected_target" && \
          "$ready" == "2" && "$phase" == "Cluster in healthy state" && \
          "$primary_class" == "$expected_primary_class" ]]; then
      assert_cluster_healthy
      return 0
    fi
    sleep 5
  done
  die "timed out waiting for source=$expected_source target=$expected_target primary-class=$expected_primary_class"
}

migration_state() {
  local source target primary primary_class
  source="$(class_count "$SOURCE_CLASS")"
  target="$(class_count "$TARGET_CLASS")"
  primary="$(primary_name)"
  primary_class="$(pvc_json | jq -r --arg primary "$primary" '.items[] | select(.metadata.name == $primary) | .spec.storageClassName')"
  case "$source:$target:$primary_class" in
    "2:0:$SOURCE_CLASS") echo "not-started" ;;
    "1:1:$SOURCE_CLASS") echo "local-standby-ready" ;;
    "1:1:$TARGET_CLASS") echo "local-primary-ready" ;;
    "0:2:$TARGET_CLASS") echo "complete" ;;
    *) echo "unexpected(source=$source,target=$target,primary=$primary/$primary_class)" ;;
  esac
}

show_status() {
  local primary
  primary="$(primary_name)"
  log "$NAMESPACE/$CLUSTER migration state: $(migration_state)"
  echo "Primary: $primary ($(node_for_pod "$primary"))"
  pvc_json | jq -r '.items[] | "PVC: \(.metadata.name) class=\(.spec.storageClassName) volume=\(.spec.volumeName)"'
  pod_json | jq -r '.items[] | "Pod: \(.metadata.name) node=\(.spec.nodeName) phase=\(.status.phase)"'
}

preflight() {
  log "Running preflight for $NAMESPACE/$CLUSTER"
  k cnpg version >/dev/null
  assert_cluster_healthy
  assert_target_policy
  assert_archiving
  assert_known_classes
  assert_source_volumes_healthy
  assert_argocd
  assert_deployment
  show_status
  log "Preflight passed"
}

backup_name() {
  local suffix="$1"
  local name="${CLUSTER}-local-migration-${suffix}"
  [[ ${#name} -le 63 ]] || die "generated Backup name is longer than 63 characters: $name"
  echo "$name"
}

run_backup() {
  local suffix="$1"
  local name phase deadline
  name="$(backup_name "$suffix")"

  if ! k get backup.postgresql.cnpg.io "$name" -n "$NAMESPACE" >/dev/null 2>&1; then
    if [[ "$EXECUTE" != true ]]; then
      log "DRY RUN: would create CNPG backup $NAMESPACE/$name"
      return 0
    fi
    log "Creating CNPG backup $NAMESPACE/$name"
    k cnpg backup "$CLUSTER" -n "$NAMESPACE" --backup-name "$name"
  fi

  phase="$(k get backup.postgresql.cnpg.io "$name" -n "$NAMESPACE" -o jsonpath='{.status.phase}')"
  if [[ "$phase" == "completed" ]]; then
    log "Backup $name already completed"
    return 0
  fi
  [[ "$EXECUTE" == true ]] || die "backup $name exists in phase '$phase'; use --execute to wait"

  deadline=$(( $(date +%s) + TIMEOUT_SECONDS ))
  while (( $(date +%s) < deadline )); do
    phase="$(k get backup.postgresql.cnpg.io "$name" -n "$NAMESPACE" -o jsonpath='{.status.phase}')"
    log "backup $name phase: ${phase:-pending}"
    [[ "$phase" == "completed" ]] && return 0
    case "$phase" in failed|error) die "backup $name failed" ;; esac
    sleep 5
  done
  die "timed out waiting for backup $name"
}

replace_standby() {
  local source target primary standby count
  source="$(class_count "$SOURCE_CLASS")"
  target="$(class_count "$TARGET_CLASS")"
  if [[ "$target" -ge 1 ]]; then
    log "Local standby stage already complete (source=$source target=$target)"
    return 0
  fi
  [[ "$source" == "2" && "$target" == "0" ]] || die "cannot replace standby from state $(migration_state)"
  assert_cluster_healthy
  primary="$(primary_name)"
  standby="$(pvc_for_class_except "$SOURCE_CLASS" "$primary")"
  count="$(printf '%s\n' "$standby" | awk 'NF {count++} END {print count+0}')"
  [[ "$count" == "1" ]] || die "expected one source standby, found $count"
  assert_replication_caught_up "$primary" "$standby"
  if [[ "$EXECUTE" != true ]]; then
    log "DRY RUN: would delete pod/$standby and pvc/$standby"
    return 0
  fi
  log "Deleting synchronized source standby pod/PVC: $standby"
  k delete "pvc/$standby" "pod/$standby" -n "$NAMESPACE"
  wait_for_state 1 1 "$SOURCE_CLASS"
}

promote_local() {
  local source target primary primary_class candidate count
  source="$(class_count "$SOURCE_CLASS")"
  target="$(class_count "$TARGET_CLASS")"
  primary="$(primary_name)"
  primary_class="$(pvc_json | jq -r --arg primary "$primary" '.items[] | select(.metadata.name == $primary) | .spec.storageClassName')"

  if [[ "$primary_class" == "$TARGET_CLASS" ]]; then
    log "Local primary stage already complete: $primary"
    return 0
  fi
  [[ "$source" == "1" && "$target" == "1" && "$primary_class" == "$SOURCE_CLASS" ]] || \
    die "cannot promote from state $(migration_state)"
  assert_cluster_healthy
  candidate="$(pvc_for_class_except "$TARGET_CLASS" "$primary")"
  count="$(printf '%s\n' "$candidate" | awk 'NF {count++} END {print count+0}')"
  [[ "$count" == "1" ]] || die "expected one local promotion candidate, found $count"
  assert_replication_caught_up "$primary" "$candidate"
  if [[ "$EXECUTE" != true ]]; then
    log "DRY RUN: would promote $candidate"
    return 0
  fi
  log "Promoting local instance $candidate"
  k cnpg promote "$CLUSTER" "$candidate" -n "$NAMESPACE"
  wait_for_state 1 1 "$TARGET_CLASS"
}

replace_remaining() {
  local source target primary primary_class standby count
  source="$(class_count "$SOURCE_CLASS")"
  target="$(class_count "$TARGET_CLASS")"
  if [[ "$source" == "0" && "$target" == "2" ]]; then
    log "Remaining source standby stage already complete"
    return 0
  fi
  primary="$(primary_name)"
  primary_class="$(pvc_json | jq -r --arg primary "$primary" '.items[] | select(.metadata.name == $primary) | .spec.storageClassName')"
  [[ "$source" == "1" && "$target" == "1" && "$primary_class" == "$TARGET_CLASS" ]] || \
    die "cannot replace remaining instance from state $(migration_state)"
  assert_cluster_healthy
  standby="$(pvc_for_class_except "$SOURCE_CLASS" "$primary")"
  count="$(printf '%s\n' "$standby" | awk 'NF {count++} END {print count+0}')"
  [[ "$count" == "1" ]] || die "expected one remaining source standby, found $count"
  assert_replication_caught_up "$primary" "$standby"
  if [[ "$EXECUTE" != true ]]; then
    log "DRY RUN: would delete pod/$standby and pvc/$standby"
    return 0
  fi
  log "Deleting synchronized remaining source pod/PVC: $standby"
  k delete "pvc/$standby" "pod/$standby" -n "$NAMESPACE"
  wait_for_state 0 2 "$TARGET_CLASS"
}

verify_final() {
  local source target primary standby primary_node standby_node pv_node
  log "Verifying final local-storage state"
  assert_cluster_healthy
  assert_target_policy
  assert_archiving
  assert_argocd
  assert_deployment
  source="$(class_count "$SOURCE_CLASS")"
  target="$(class_count "$TARGET_CLASS")"
  [[ "$source" == "0" && "$target" == "2" ]] || die "final classes are source=$source target=$target"
  primary="$(primary_name)"
  standby="$(pvc_for_class_except "$TARGET_CLASS" "$primary")"
  assert_replication_caught_up "$primary" "$standby"
  primary_node="$(node_for_pod "$primary")"
  standby_node="$(node_for_pod "$standby")"
  [[ "$primary_node" != "$standby_node" ]] || die "both instances run on $primary_node"

  while IFS=$'\t' read -r pvc pod_node volume; do
    pv_node="$(k get pv "$volume" -o json | jq -r '.spec.nodeAffinity.required.nodeSelectorTerms[].matchExpressions[] | select(.key == "kubernetes.io/hostname") | .values[0]')"
    [[ "$pv_node" == "$pod_node" ]] || die "$pvc PV is on $pv_node but pod is on $pod_node"
  done < <(pvc_json | jq -r '.items[] | [.metadata.name, .metadata.name, .spec.volumeName] | @tsv' | \
    while IFS=$'\t' read -r pvc pod volume; do printf '%s\t%s\t%s\n' "$pvc" "$(node_for_pod "$pod")" "$volume"; done)

  k exec -n "$NAMESPACE" "$primary" -c postgres -- \
    psql -U postgres -d postgres -v ON_ERROR_STOP=1 -Atqc \
    "SELECT current_database(), pg_is_in_recovery(), count(*) FROM pg_database" >/dev/null
  show_status
  log "Final verification passed"
}

dry_run_all() {
  local state
  preflight
  state="$(migration_state)"
  echo
  log "DRY RUN migration plan from state: $state"
  if [[ "$state" == "complete" ]]; then
    echo "Migration stages 1-5 are already complete and would be skipped."
    echo "The post-migration backup $(backup_name post) would be created or awaited."
    echo "Re-run with --stage all --execute to finish that idempotent action."
    return 0
  fi
  echo "1. Create/wait for backup $(backup_name pre)"
  echo "2. Replace the source-class standby with a $TARGET_CLASS standby"
  echo "3. Promote the synchronized $TARGET_CLASS standby"
  echo "4. Replace the remaining $SOURCE_CLASS standby"
  echo "5. Verify two local PVCs on distinct nodes and zero replication lag"
  echo "6. Create/wait for backup $(backup_name post)"
  echo "Re-run with --stage all --execute to perform or resume these actions."
}

run_all() {
  preflight
  if [[ "$(class_count "$TARGET_CLASS")" == "0" ]]; then
    run_backup pre
  else
    log "Migration already started; preserving the existing pre-migration backup gate"
    local pre_name
    pre_name="$(backup_name pre)"
    if k get backup.postgresql.cnpg.io "$pre_name" -n "$NAMESPACE" >/dev/null 2>&1; then
      run_backup pre
    else
      log "No stable pre-backup named $pre_name; continuing because local PVCs already exist"
    fi
  fi
  replace_standby
  promote_local
  replace_remaining
  verify_final
  run_backup post
}

case "$STAGE" in
  status) show_status ;;
  preflight) preflight ;;
  backup-pre) assert_cluster_healthy; assert_archiving; run_backup pre ;;
  replace-standby) preflight; replace_standby ;;
  promote) preflight; promote_local ;;
  replace-remaining) preflight; replace_remaining ;;
  verify) verify_final ;;
  backup-post) verify_final; run_backup post ;;
  all)
    if [[ "$EXECUTE" == true ]]; then
      run_all
    else
      dry_run_all
    fi
    ;;
esac
