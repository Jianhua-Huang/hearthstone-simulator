"""Opt-in fixed CN37 candidate matches, separate from formal Standard support.

The checked-in catalog is complete for this explicitly named candidate domain.
It is not a certified legality pool, a pack-opening pool, or a live-clock feed.
"""
from dataclasses import dataclass
from pathlib import Path

from .cards import build_registry
from .cards.candidate_generation_catalog import BATCH_HASH,load_batch
from .engine.construction import DeckPolicy,MatchSetup
from .engine.game import Game
from .engine.pools import GenerationContext,PoolDefinition,PoolMember
from .engine.registry import Registry
from .targets import TargetValidationError,_load_json,canonical_digest

SOURCE_PATH=Path(__file__).resolve().parents[1]/'data/cards/integration-target-cn37.json'
SOURCE_FACTS_HASH='13f881a9e3544a5449b153094e9c4f8b72973cc8df450635f76ab42e90a64a2a'
FORMAT_VERSION='cn37-pre-black-empire-candidate-v1'
POOL_ID='constructed.cards'


def load_source_facts():
    """Bind semantic source facts; historical progress counters are not inputs."""
    data=_load_json(SOURCE_PATH)
    keys=('official_patch','region','active_formats','deferred_formats',
        'standard_candidate_policy','candidate_inventory_is_formal_pool',
        'reachable_content_inventory_complete','official_effective_at',
        'preloaded_expansion','local_client_version','client_data_matches_target_patch',
        'hotfix_set_complete','standard_pool_complete')
    try:
        facts={k:data[k]for k in keys}
        facts['frozen_source']={k:data['additional_frozen_source'][k]for k in('repository','commit','client_version')}
        facts['normalized_source_sha256']=data['current_standard_candidate_source']['sha256']
    except(KeyError,TypeError)as exc:
        raise TargetValidationError('CN37 candidate binding lost required source facts')from exc
    if canonical_digest(facts)!=SOURCE_FACTS_HASH:
        raise TargetValidationError('CN37 candidate source/phase changed and needs a reviewed new binding')
    return facts


@dataclass(frozen=True)
class CandidateFormat:
    registry: Registry
    target_id: str
    binding_digest: str
    root_card_ids: tuple[str,...]
    policy: DeckPolicy
    context: GenerationContext
    effective_from: str
    effective_until: str
    frozen_client_version: str

    @property
    def formal_pool_complete(self):return False

    def require_formal(self):
        raise TargetValidationError('This fixed CN37 candidate format is experimental; M0 legality/hotfix/generation evidence and M6 CN calibration remain incomplete')

    def match_setup(self,decks,*,seed=0,first_player=None,board_id=None):
        return MatchSetup(decks,self.policy,'GAME_005',seed,first_player,board_id)

    def new_game(self,decks,*,seed=0,first_player=None,board_id=None):
        return Game.from_decks(self.match_setup(decks,seed=seed,first_player=first_player,
            board_id=board_id),self.registry)


def build_cn37_candidate_format():
    """Bind the full frozen roster without installing it in default registries.

    Fixed future phases require their own reviewed binding. No wall clock is
    read, so this historical phase and its saved matches remain reproducible.
    """
    facts=load_source_facts();catalog=load_batch();roots=tuple(catalog['candidate_root_ids'])
    if(catalog['policy']['region']!=facts['region']or catalog['policy']['patch']!=facts['official_patch']or
            catalog['policy']['source_commit']!=facts['frozen_source']['commit']):
        raise TargetValidationError('Candidate catalog does not belong to its fixed target source')
    registry=build_registry()
    # Every root is needed for deck use, including roots excluded from random
    # generation. Missing implementations never shrink the declared inventory.
    for cid in roots:registry.card(cid)
    companions={cid for spec in registry.fabled.values()if spec.source_card_id in roots
        for cid in spec.companion_card_ids}
    allowed=tuple(sorted(set(roots)|companions))
    binding=canonical_digest(dict(format=FORMAT_VERSION,source=SOURCE_FACTS_HASH,
        catalog=BATCH_HASH,content=registry.version,allowed=allowed))
    target_id=FORMAT_VERSION+'-'+binding[:16]
    policy=DeckPolicy(target_id+'.deck',target_id,'experimental',allowed,pool_complete=False)
    context=GenerationContext(target_id,'experimental')
    registry.register_pool(PoolDefinition(POOL_ID,'source-pinned-'+binding,target_id,'experimental',
        tuple(PoolMember(cid)for cid in roots),complete=True))
    registry.validate()
    return CandidateFormat(registry,target_id,binding,roots,policy,context,
        facts['official_effective_at'],facts['preloaded_expansion']['formal_launch'],
        facts['frozen_source']['client_version'])
