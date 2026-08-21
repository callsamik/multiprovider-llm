import subprocess
import sys


def test_client_import_does_not_load_ranking_modules():
    script = (
        "import sys\n"
        "import multiprovider_llm.client\n"
        "loaded = set(sys.modules)\n"
        "assert 'multiprovider_llm.routing.rank' not in loaded\n"
        "assert 'multiprovider_llm.routing.pool' not in loaded\n"
        "assert 'multiprovider_llm.routing.scoring' not in loaded\n"
        "assert 'multiprovider_llm.routing.chain' in loaded\n"
    )
    subprocess.run([sys.executable, "-c", script], check=True)
