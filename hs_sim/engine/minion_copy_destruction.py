"""One-shot current-face minion identities across board, hands and decks."""
from dataclasses import dataclass
from .effects import Effect,DestroyBatch,_integer
from .errors import ResolutionError,ResolutionLimitExceeded
from .model import CardType,Zone
from .zones import (CardReference,DestroyStoredBatch,commit_stored_destruction_batch,
    publish_stored_destruction,source_exists)


@dataclass(frozen=True)
class DestroyMinionCopies(Effect):
    source_id:int

    def __post_init__(self):_integer(self.source_id,'minion-copy destruction source',1)


def destroy_minion_copies(r,effect):
    from .resolver import destroy_batch
    effect.__post_init__();source_exists(r,effect.source_id)
    board=[];identities=set()
    for pid in(1,2):
        for eid in r.player(pid).board:
            e=r.state.entities[eid];definition=r.registry.card(e.card_id)
            if (e.kind==CardType.MINION and definition.interactable is None and
                    e.active and not e.doomed and e.health>0):
                board.append(eid);identities.add(e.card_id)
    if not board:return()
    stored=[]
    for pid in(1,2):
        for zone in(Zone.HAND,Zone.DECK):
            for eid in getattr(r.player(pid),zone.value):
                e=r.state.entities[eid]
                if e.card_id not in identities:continue
                definition=r.registry.card(e.card_id)
                if e.kind!=CardType.MINION or definition.kind!=CardType.MINION or definition.interactable is not None:
                    raise ResolutionError('A current minion identity cannot borrow another physical card kind')
                stored.append(CardReference.capture(e))
    if len(board)+len(stored)>r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Minion-copy destruction exceeds its original physical batch budget')
    request=DestroyStoredBatch(tuple(stored),effect.source_id)
    # Every stored departure commits before any explicit destruction notice.
    # The ordinary board batch then marks every original living body, and the
    # existing scheduler owns death, reactions, intrinsic bodies and Reborn.
    targets=commit_stored_destruction_batch(r,request)
    destroy_batch(r,DestroyBatch(tuple(board),effect.source_id))
    for card,entity in targets:publish_stored_destruction(r,card,entity,effect.source_id,request.reveal)
    return()


def register(mechanics):mechanics.register(DestroyMinionCopies,destroy_minion_copies)
