"""Run baseline controls and remove-hook mutation; always restore production code."""
from pathlib import Path
import subprocess
import sys

path = Path('app/manager.py')
original = path.read_text()
python = sys.executable
try:
    path.write_bytes(subprocess.check_output(['git', 'show', 'HEAD:app/manager.py']))
    with open('.orchestra/tasks/528/baseline.log', 'w') as output:
        result = subprocess.run([python, '-m', 'pytest', '-q',
            'tests/test_fan_barrier_gates.py::test_message_without_sender_is_never_buffered',
            'tests/test_task_tracker_integration.py::test_t3_merge_operation_replay_does_not_repeat_git_or_lose_task_outcome'], stdout=output, stderr=subprocess.STDOUT)
        output.write(f'\nEXIT_CODE={result.returncode}\n')
    call = '        await asyncio.to_thread(self._cleanup_cli_home, session_id)\n'
    assert original.count(call) == 1
    path.write_text(original.replace(call, ''))
    with open('.orchestra/tasks/528/mutation.log', 'w') as output:
        result = subprocess.run([python, '-m', 'pytest', '-q', 'tests/test_manager.py', '-k', 'test_remove_cleans_only_its_home'], stdout=output, stderr=subprocess.STDOUT)
        output.write(f'\nEXIT_CODE={result.returncode}\n')
    assert result.returncode == 1, 'removing cleanup must fail the committed positive tests'
finally:
    path.write_text(original)
