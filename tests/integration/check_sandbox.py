import os
from pathlib import Path
import tempfile
import subprocess
from charisma.repair import run_check

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);candidate=root/'candidate';candidate.mkdir()
    hidden=root/'private.txt';hidden.write_text('must not be mounted')
    script='''import os,socket
from pathlib import Path
assert not Path('/private.txt').exists()
assert not os.environ.get('OPENAI_API_KEY')
assert os.getuid()!=0
try:
    Path('/etc/charisma-test').write_text('not allowed')
    raise AssertionError('Root filesystem was writable')
except PermissionError:pass
except OSError:pass
assert [name for _,name in socket.if_nameindex()]==['lo']
print('Isolated checks passed')
'''
    (candidate/'check.py').write_text(script)
    result=run_check(candidate,['python','check.py'],container_image=os.environ['CHARISMA_TEST_IMAGE'])
    assert result['passed'],result['output_tail']
    print(result['output_tail'])

    timeout_result=run_check(candidate,['python','-c','import time;time.sleep(60)'],timeout=1,container_image=os.environ['CHARISMA_TEST_IMAGE'])
    assert timeout_result['timed_out'] and not timeout_result['passed']
    remaining=subprocess.run(['docker','ps','--filter','name=charisma-test-','--format','{{.Names}}'],capture_output=True,text=True,check=True)
    assert not remaining.stdout.strip(), 'Timed-out test container was left running'
    print('Timed-out isolated test container was removed.')
