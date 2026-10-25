"""User-authorized temporary exclusions; these are not official pool bans."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_restrictions import AssembleLocalRestriction
from hs_sim.targets import TargetValidationError, canonical_digest

DATA = Path(__file__).resolve().parents[2] / 'data/support/assemble-local-restrictions-v1.json'
PIN = '1ee2636b91afe5810bbf610c096b8fa08912472bf542662f3d49fd1d1eded18c'


def load_policy():
    data = json.loads(DATA.read_text(encoding='utf-8'))
    if (canonical_digest(data) != PIN or data['official_ban'] is not False or
            data['official_incompatibility_confirmed'] is not False or
            data['scope'] != 'local-assemble-only' or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256']
                for row in data['entries'])):
        raise TargetValidationError('Local Assemble restrictions changed their reviewed scope or originals')
    return data


def register_assemble_local_restrictions(registry):
    for row in load_policy()['entries']:
        profile = AssembleLocalRestriction(**(row['profile'] |
            {'suffix_timings': tuple(row['profile']['suffix_timings'])}))
        if canonical_digest(asdict(registry.card(profile.card_id))) != row['definition_sha256']:
            raise TargetValidationError('Local Assemble restriction changed a complete ordinary card')
        registry.register_assemble_local_restriction(profile)
