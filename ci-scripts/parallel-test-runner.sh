#!/usr/bin/bash

# It can passed as a parameter
MAX_CONCURRENT_TESTS=${1:-5}
PLAN=${2:-connect}

FEELING_SAFE=
if [ "$PLAN" == "local" ]; then
    FEELING_SAFE=--feeling-safe
fi

TMT_WORKDIR_ROOT=${TMT_WORKDIR_ROOT:-"/var/tmp/tmt"}

# Boolean indicator, that prepare phase already finished during parallel test run
PTR_PREPARE_FINISHED=""

# TMT_RUN_OPTIONS need to contain all important options for tmt execution
if [ -n "$TMT_RUN_OPTIONS" ]; then
    # It's not possible to pass array type variable through environment, so conversion needed
    read -a TMT_RUN_OPTIONS <<< "$TMT_RUN_OPTIONS"
else
    # By default run tests against locally provisioned VM
    TMT_RUN_OPTIONS=( -eNODE=aib-tests-10 plan --name "$PLAN" )
fi

format_time() {
    local exec_time=$1
    ((h=exec_time/3600))
    ((m=(exec_time%3600)/60))
    ((s=exec_time%60))
    printf "%02d:%02d:%02d" $h $m $s
 }

format_test_id() {
    local test_run_idx=$1
    local test_name=$2
    echo "$(printf "%02d" $(( test_run_idx + 1)))-$test_name"
}

print_list() {
    local items=("$@")

    for item in "${items[@]}"; do
        echo "    ${item}"
    done
}

execute_test() {
    local test_run_idx=$1
    local test_name=${DISCOVERED_TESTS[$test_run_idx]}
    local start_time
    local test_id

    test_id="$(format_test_id "$test_run_idx" "$test_name")"
    if [ -d "${TMT_WORKDIR_ROOT}/${test_id}" ]; then
        echo "Skipping test '$test_name', test run directory '${TMT_WORKDIR_ROOT}/${test_id}' exists!"
        SKIPPED_TESTS+=("$test_name")
        SUCCESSFUL_TESTS=$((SUCCESSFUL_TESTS + 1))
        return 0
    fi

    echo "Starting test '$test_name'"
    start_time=$(date +%s)
    # TODO: simplify when https://github.com/teemtee/tmt/issues/2757 is fixed
    tmt -c arch="$(arch)" \
        -q \
        $FEELING_SAFE \
        run \
        -i "$test_id" \
        -ePTR_PREPARE_FINISHED="$PTR_PREPARE_FINISHED" \
        "${TMT_RUN_OPTIONS[@]}" \
        test --name "$test_name" \
        discover prepare provision execute -h tmt --no-progress-bar report &
    local pid=$!
    TEST_START_TIME[$pid]=$start_time
    TEST_NAMES[$pid]=$test_name
    TEST_IDS[$pid]=$test_id
}

START_TIME=$(date +%s)

echo "Preparing tests execution"
# Execute phases up to prepare
PREPARE_TESTS_ID="$(format_test_id "-1" "prepare-tests")"
tmt -c arch="$(arch)" \
    -q \
    $FEELING_SAFE \
    run \
    -i "$PREPARE_TESTS_ID" \
    -B execute \
    "${TMT_RUN_OPTIONS[@]}"

END_TIME=$(date +%s)
echo "Finished test preparation, execution time: $(format_time $((END_TIME - START_TIME)))"

PTR_PREPARE_FINISHED="yes"

# Gather discovered tests
mapfile -t DISCOVERED_TESTS< \
    <(grep "name:" < "$TMT_WORKDIR_ROOT/$PREPARE_TESTS_ID/plans/$PLAN/discover/tests.yaml" | sed 's/.*tests\///')
TEST_COUNT=${#DISCOVERED_TESTS[@]}


declare -A TEST_NAMES
declare -A TEST_IDS
declare -A TEST_START_TIME
INDEX=0
SUCCESSFUL_TESTS=0
FAILED_TESTS=()
SKIPPED_TESTS=()

# Start max allowed test executed at the beginning
while [[ $INDEX -lt $TEST_COUNT && ${#TEST_NAMES[@]} -lt $MAX_CONCURRENT_TESTS ]]; do
    execute_test "$INDEX"
    INDEX=$(( INDEX + 1 ))
    sleep 0.1  # Small stagger
done

# Monitor and execute new tests when previous finished
while [[ ${#TEST_NAMES[@]} -gt 0 ]]; do
    # Check for completed builds
    for pid in "${!TEST_NAMES[@]}"; do
        if ! kill -0 "$pid" 2>/dev/null; then
            # Test finished
            wait "$pid"
            exit_code=$?
            exec_time="$(format_time $(($(date +%s) - ${TEST_START_TIME[$pid]})))"
            if [[ $exit_code -ne 0 ]]; then
                echo "Test '${TEST_NAMES[$pid]}' failed in $exec_time"
                FAILED_TESTS+=("${TEST_NAMES[$pid]}")
            else
                echo "Test '${TEST_NAMES[$pid]}' successful in $exec_time"
                SUCCESSFUL_TESTS=$((SUCCESSFUL_TESTS + 1))
            fi
            # Create link for easier results access
            ( cd "${TMT_WORKDIR_ROOT}/${TEST_IDS[$pid]}" && \
                ln -s "plans/${PLAN}/execute/data/guest/default-0/tests/${TEST_NAMES[$pid]}-1" test-results )

            unset "TEST_START_TIME[$pid]"
            unset "TEST_NAMES[$pid]"
            unset "TEST_IDS[$pid]"

            # Start next test if available
            if [[ $INDEX -lt $TEST_COUNT ]]; then
                execute_test "$INDEX"
                INDEX=$(( INDEX + 1 ))
            fi
        fi
    done

    # Brief pause before next check
    sleep 1
done

# Execute cleanup
echo "Cleaning up tests execution"
tmt -c arch="$(arch)" \
    -q \
    $FEELING_SAFE \
    run \
    --last \
    -A execute \
    "${TMT_RUN_OPTIONS[@]}"

END_TIME=$(date +%s)

echo "Tests execution finished, overall execution time: $(format_time $((END_TIME - START_TIME)))"

if [[ $TEST_COUNT -ne $SUCCESSFUL_TESTS ]]; then
    echo "Only $SUCCESSFUL_TESTS/$TEST_COUNT finished successfully, following tests FAILED:"
    print_list "${FAILED_TESTS[@]}"
    exit 1
fi

if [[ "${#SKIPPED_TESTS[@]}" -gt 0 ]]; then
    echo "Following tests were SKIPPED:"
    print_list "${SKIPPED_TESTS[@]}"
    exit 2
fi

echo "All $TEST_COUNT tests finished successfully."
exit 0
