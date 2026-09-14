import importlib.util, json
from pathlib import Path
P=Path(__file__).resolve().parents[1]/"protected"/"relay_driver.py"
spec=importlib.util.spec_from_file_location("relay002",P)
m=importlib.util.module_from_spec(spec)
import sys
sys.modules["relay002"]=m
spec.loader.exec_module(m)

def test_hash():
    assert m.sha256_text("abc")=="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"

def test_json():
    assert m.extract_last_json('a {"x":1} b {"trial":2}')=={"trial":2}

def test_contract():
    assert m.MAX_WAIT==1200
    assert m.REQUIRED_MARKERS==("Temporary Chat","Extended")
    assert m.GEMINI_URL=="https://gemini.google.com/app"

def test_fingerprint():
    fp=m.host_fingerprint()
    assert len(fp["sha256"])==64
