from pathlib import Path
import zipfile

from scripts.install_codex_skill import install_skill


def test_install_skill_replaces_one_skill_and_cleans_archive(tmp_path):
    archive = tmp_path / 'memoir-place-journey.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('memoir-place-journey/SKILL.md', 'new skill')
        bundle.writestr('memoir-place-journey/references/contract.md', 'contract')

    skill_root = tmp_path / 'codex-home'
    target = skill_root / 'skills' / 'memoir-place-journey'
    target.mkdir(parents=True)
    (target / 'old.txt').write_text('old')

    install_skill(str(archive), 'memoir-place-journey', str(skill_root))

    assert (target / 'SKILL.md').read_text() == 'new skill'
    assert (target / 'references' / 'contract.md').read_text() == 'contract'
    assert not (target / 'old.txt').exists()
    assert not archive.exists()
