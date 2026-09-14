import importlib.util
from pathlib import Path
P=Path(__file__).resolve().parents[1]/'protected'/'relay_driver.py'
spec=importlib.util.spec_from_file_location('relay',P); m=importlib.util.module_from_spec(spec); import sys; sys.modules['relay']=m; spec.loader.exec_module(m)
def test_extract_last_json():
    x=m.extract_last_json('a {"x":1} b {"experiment":"RIL-RELAY-001","trial":2}')
    assert x['trial']==2
def test_hash_stable():
    assert m.sha256_text('abc')=='ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
def test_contract_constants():
    assert m.MAX_WAIT==1200
    assert m.REQUIRED_MARKERS==('Temporary Chat','Extended')
