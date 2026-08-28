#!/usr/bin/env sh
set -eu

DATABASE="workflow-v19"
CONFIG="../config/noc-prod.conf"
SUITE="gate"
UPGRADE="1"

usage() {
    cat <<'EOF'
Usage:
  sh ./naga/workflow/engine/workflow_engine/scripts/run_mtf_workflow_regression.sh [options]

Options:
  -d, --database DB       Database to test. Default: workflow-v19
  -c, --config PATH       Odoo config path from core-odoo. Default: ../config/noc-prod.conf
  -s, --suite SUITE       gate or full-backend. Default: gate
      --no-upgrade        Run tests without upgrading modules
  -h, --help              Show this help

Examples:
  sh ./naga/workflow/engine/workflow_engine/scripts/run_mtf_workflow_regression.sh --suite gate
  sh ./naga/workflow/engine/workflow_engine/scripts/run_mtf_workflow_regression.sh --database preprod-regression --suite gate
  sh ./naga/workflow/engine/workflow_engine/scripts/run_mtf_workflow_regression.sh --database preprod-regression --suite full-backend

Safety:
  Do not run this against an active shared/live database. It upgrades modules unless --no-upgrade is used.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        -d|--database)
            DATABASE="${2:?Missing database value}"
            shift 2
            ;;
        -c|--config)
            CONFIG="${2:?Missing config value}"
            shift 2
            ;;
        -s|--suite)
            SUITE="${2:?Missing suite value}"
            shift 2
            ;;
        --no-upgrade)
            UPGRADE="0"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [ "$SUITE" != "gate" ] && [ "$SUITE" != "full-backend" ]; then
    echo "Invalid suite '$SUITE'. Use: gate or full-backend" >&2
    exit 2
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SEARCH_DIR="$SCRIPT_DIR"
REPO_ROOT=""

while [ "$SEARCH_DIR" != "/" ]; do
    if [ -f "$SEARCH_DIR/core-odoo/odoo-bin" ]; then
        REPO_ROOT="$SEARCH_DIR"
        break
    fi
    SEARCH_DIR=$(dirname -- "$SEARCH_DIR")
done

if [ -z "$REPO_ROOT" ]; then
    echo "Cannot find repository root with core-odoo/odoo-bin from $SCRIPT_DIR" >&2
    exit 2
fi

ODOO_ROOT="$REPO_ROOT/core-odoo"
MODULES="workflow_inventory,workflow_engine,workflow_studio,medical_request"

GATE_TAGS="/medical_request:TestMTFStabilization.test_shared_delegate_can_execute_mtf_workflow_action_without_child_write_access,/workflow_engine:TestWorkflowRuntimeServices.test_conditional_event_empty_condition_uses_default_flow_and_ignores_route_guard,/workflow_engine:TestWorkflowRuntimeServices.test_conditional_event_invalid_condition_uses_default_flow_and_warns,/workflow_engine:TestWorkflowRuntimeServices.test_group_link_domain_resolved_against_child_model_field,/workflow_engine:TestWorkflowRuntimeServices.test_group_link_domain_supports_relational_request_owner_path,/workflow_engine:TestWorkflowRuntimeServices.test_group_link_domains_route_distinct_groups_by_request_value,/workflow_engine:TestWorkflowRuntimeServices.test_group_link_domains_block_when_no_rule_matches,/workflow_engine:TestWorkflowRuntimeServices.test_visible_buttons_actor_approval_group_visible,/workflow_engine:TestWorkflowRuntimeServices.test_visible_buttons_actor_approval_group_hidden_for_non_member,/workflow_engine:TestWorkflowRuntimeServices.test_visible_buttons_actor_has_approval_group_helper_visible,/workflow_engine:TestWorkflowRuntimeServices.test_visible_buttons_actor_has_approval_group_helper_hidden_for_non_member"
EXPECTED_GATE_TESTS="11"
FULL_BACKEND_TAGS="/medical_request,/workflow_engine,/workflow_studio"

if [ "$SUITE" = "full-backend" ]; then
    TEST_TAGS="$FULL_BACKEND_TAGS"
else
    TEST_TAGS="$GATE_TAGS"
fi

cd "$ODOO_ROOT"

echo "Running $SUITE regression on database '$DATABASE' with config '$CONFIG'"
echo "Repository root: $REPO_ROOT"
echo "Modules: $MODULES"
echo "Tags: $TEST_TAGS"

if [ "$UPGRADE" = "1" ]; then
    set -- run python odoo-bin \
        -c "$CONFIG" \
        -d "$DATABASE" \
        -u "$MODULES" \
        --test-enable \
        --test-tags "$TEST_TAGS" \
        --stop-after-init \
        --no-http \
        --log-level=test
else
    set -- run python odoo-bin \
        -c "$CONFIG" \
        -d "$DATABASE" \
        --test-enable \
        --test-tags "$TEST_TAGS" \
        --stop-after-init \
        --no-http \
        --log-level=test
fi

OUTPUT_FILE="${TMPDIR:-/tmp}/mtf-workflow-regression-$$.log"
trap 'rm -f "$OUTPUT_FILE"' EXIT HUP INT TERM

if uv "$@" >"$OUTPUT_FILE" 2>&1; then
    cat "$OUTPUT_FILE"
else
    STATUS=$?
    cat "$OUTPUT_FILE"
    exit "$STATUS"
fi

if [ "$SUITE" = "gate" ] && ! grep -q "0 failed, 0 error(s) of $EXPECTED_GATE_TESTS tests" "$OUTPUT_FILE"; then
    echo "Gate coverage mismatch: expected $EXPECTED_GATE_TESTS tests to run." >&2
    exit 1
fi
