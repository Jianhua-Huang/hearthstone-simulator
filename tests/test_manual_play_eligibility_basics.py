"""Physical storage is independent of permission to play a current face manually."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition, CardType, Game, IllegalAction, PlayCard,
    PlayerSetup, Registry, ResolutionError, Scenario, SelectChoice, SnapshotError, Zone)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Draw, GainArmor,
    InvokeBehavior, RequestChoice)
from hs_sim.engine.hand_upgrades import UpgradeHandCard
from hs_sim.engine.play_history import prepare_play
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import PlayFromHand, Resolution
from hs_sim.engine.spell_cost_proof import (capture_hand_cost_proof,
    validate_compact_hand_costs, validate_hand_cost_proof)
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest

ROOT=Path(__file__).resolve().parents[1]
PIN='9c2b8cba397c45c79c60b6621a6f0b80b16cb4287d13b2926da3f2c2fb327db9'


def evidence():
    p=json.loads((ROOT/'data/support/manual-play-eligibility-basics.json').read_bytes())
    if canonical_digest(p)!=PIN:raise ValueError('Manual play eligibility full raw changed')
    return p


def registry(permit=False):
    r=Registry('manual-play-eligibility-independent-v1')
    r.register_card(CardDefinition('mp.hero','Diagnostic hero',CardType.HERO,health=30))
    # These are diagnostics for the primitive, not executable Shadow of Demise cards.
    r.register_behavior('mp.marker',lambda c:(GainArmor(c.player_id,1),))
    r.register_card(CardDefinition('mp.locked','Diagnostic native locked spell',CardType.SPELL,
        manual_playable=permit,on_play='mp.marker'))
    r.register_card(CardDefinition('mp.open','Diagnostic unlocked current face',CardType.SPELL,on_play='mp.marker'))
    r.register_card(CardDefinition('mp.minion','Diagnostic locked minion',CardType.MINION,
        cost=1,health=2,manual_playable=permit))
    r.register_card(CardDefinition('mp.stock','Diagnostic stock',CardType.MINION,health=1))
    def first(c):
        s=c.state
        return CardReference.capture(s.entities[next(i for i in s.players[c.player_id].hand
            if s.entities[i].card_id in ('mp.locked','mp.open'))])
    def fail(c):raise ResolutionError('Diagnostic continuation failure')
    r.register_behavior('mp.fail',fail)
    bodies={
        'create':lambda c:(AddToHand(c.player_id,'mp.locked',c.source_id),),
        'draw':lambda c:(Draw(c.player_id),),
        'copy':lambda c:(CopyCard(first(c),c.player_id,source_id=c.source_id),),
        'basecopy':lambda c:(CopyCard(first(c),c.player_id,mode='base',source_id=c.source_id),),
        'unlock':lambda c:(UpgradeHandCard(first(c),'mp.open',c.source_id),),
        'lock':lambda c:(UpgradeHandCard(first(c),'mp.locked',c.source_id),),
        'reset':lambda c:(MoveCard(first(c),c.player_id,Zone.DECK,'top',reset=True,source_id=c.source_id),),
        'bypass':lambda c:(PlayFromHand(PlayCard(c.player_id,first(c).entity_id)),),
        'waitcreate':lambda c:(RequestChoice(c.player_id,(
            ChoiceOption('create','Create',(AddToHand(c.player_id,'mp.locked',c.source_id),)),
            ChoiceOption('fail','Fail',(InvokeBehavior('mp.fail',c.source_id,c.player_id),))),c.source_id),),
    }
    for name,fn in bodies.items():
        r.register_behavior('mp.'+name,fn)
        r.register_card(CardDefinition('mp.'+name,'Diagnostic '+name,CardType.SPELL,on_play='mp.'+name))
    return r


class ManualPlayEligibilityTests(unittest.TestCase):
    def game(self,hand=('mp.locked',),deck=('mp.stock',)*12,enemy=('mp.locked',),permit=False,mana=10):
        return Game.from_scenario(Scenario((
            PlayerSetup('mp.hero',hand=hand,deck=deck,max_mana=10,mana=mana),
            PlayerSetup('mp.hero',hand=enemy,deck=('mp.stock',)*12)),seed=71),registry(permit))

    def card(self,g,name='mp.locked'):
        return next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name)

    def play(self,g,name):return g.apply(PlayCard(1,self.card(g,name)))

    def portable(self,g,permit=False):
        s=g.snapshot()
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),registry(permit)).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry(permit)).snapshot(),s)
        return s

    def blocked(self,g,eid):
        s=g.snapshot()
        with self.assertRaisesRegex(IllegalAction,'manually played'):g.apply(PlayCard(1,eid))
        self.assertEqual(g.snapshot(),s)
        self.assertFalse(any(isinstance(a,PlayCard) and a.entity_id==eid for a in g.legal_actions()))

    def test_raw_native_flag_is_pinned_and_full_real_card_is_explicitly_unadapted(self):
        p=evidence();raw={x['id']:x for x in p['records']}
        for name in ('RLK_567','CORE_RLK_567'):
            self.assertEqual(raw[name]['tags']['LITERALLY_UNPLAYABLE'],1)
            self.assertIn('transform this into a copy',raw[name]['text_en'])
            self.assertNotIn(name,registry().cards)
        for key in ('full_shadow_of_demise_adapted','formal_pool_verified','CN_calibrated','all_314_rows_classified'):
            self.assertFalse(p[key])
        self.assertEqual(p['new_real_card_adapters'],0)

    def test_strict_boolean_and_structural_storage_are_separate(self):
        d=registry().card('mp.locked');self.assertTrue(d.hand_playable);self.assertFalse(d.manual_playable)
        for value in (0,1,None,'false'):
            with self.assertRaisesRegex(ValueError,'boolean'):
                Registry('bad').register_card(replace(d,manual_playable=value,on_play=None))
        for definition in (CardDefinition('bad','bad',CardType.HERO,health=30,manual_playable=False),
                CardDefinition('bad','bad',CardType.HERO_POWER,manual_playable=False),
                replace(d,choice_only=True,on_play=None)):
            with self.assertRaisesRegex(ValueError,'physical hand/deck'):
                Registry('bad').register_card(definition)

    def test_zero_quote_and_available_resources_never_grant_manual_permission(self):
        g=self.game(mana=0);eid=self.card(g);self.assertEqual(g.quote_cost(eid).amount,0)
        self.blocked(g,eid);self.assertEqual(g.state.play_history,[]);self.assertFalse(g.events)
        self.portable(g)

    def test_locked_nonspell_is_stored_but_cannot_enter_paid_hand_route(self):
        g=self.game(hand=('mp.minion',));self.blocked(g,self.card(g,'mp.minion'))
        self.assertEqual(g.state.players[1].board,[]);self.assertEqual(g.state.players[1].mana,10)
        self.portable(g)

    def test_creation_and_physical_deck_draw_preserve_the_native_prohibition(self):
        g=self.game(hand=('mp.create','mp.draw'),deck=('mp.locked','mp.stock'))
        self.play(g,'mp.create');created=self.card(g);self.blocked(g,created)
        self.play(g,'mp.draw');drawn=g.state.players[1].hand[-1]
        self.assertNotEqual(drawn,created);self.assertEqual(g.state.entities[drawn].card_id,'mp.locked')
        self.blocked(g,drawn);self.portable(g)

    def test_current_and_base_copies_of_locked_face_remain_locked(self):
        g=self.game(hand=('mp.locked','mp.copy','mp.basecopy'))
        original=self.card(g)
        for name in ('mp.copy','mp.basecopy'):
            self.play(g,name);new=g.state.players[1].hand[-1]
            self.assertNotEqual(new,original);self.blocked(g,new)
        self.portable(g)

    def test_stored_transform_and_current_copy_use_the_new_face_permission(self):
        g=self.game(hand=('mp.locked','mp.unlock','mp.copy'));eid=self.card(g)
        self.play(g,'mp.unlock');self.assertEqual(g.state.entities[eid].card_id,'mp.open')
        self.play(g,'mp.copy');copied=g.state.players[1].hand[-1]
        self.assertEqual(g.state.entities[copied].card_id,'mp.open')
        for i in (eid,copied):g.apply(PlayCard(1,i))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2);self.portable(g)

    def test_transform_to_locked_face_removes_permission_without_changing_storage(self):
        g=self.game(hand=('mp.open','mp.lock'));eid=self.card(g,'mp.open')
        self.play(g,'mp.lock');self.assertEqual(g.state.entities[eid].card_id,'mp.locked')
        self.blocked(g,eid);self.portable(g)

    def test_base_copy_and_reset_use_current_printed_face_after_transform(self):
        g=self.game(hand=('mp.locked','mp.unlock','mp.basecopy','mp.reset','mp.draw'));eid=self.card(g)
        self.play(g,'mp.unlock');self.play(g,'mp.basecopy');copied=g.state.players[1].hand[-1]
        self.assertEqual(g.state.entities[copied].card_id,'mp.open')
        self.play(g,'mp.reset');self.assertEqual(g.state.entities[eid].zone,Zone.DECK)
        self.play(g,'mp.draw');self.assertEqual(g.state.entities[eid].card_id,'mp.open')
        for i in (eid,copied):g.apply(PlayCard(1,i))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2);self.portable(g)
        locked=self.game(hand=('mp.locked','mp.reset','mp.draw'));eid=self.card(locked)
        self.play(locked,'mp.reset');self.play(locked,'mp.draw')
        self.assertEqual(locked.state.entities[eid].card_id,'mp.locked');self.blocked(locked,eid)
        self.portable(locked)

    def test_internal_manual_entry_cannot_bypass_gate_and_outer_action_rolls_back(self):
        g=self.game(hand=('mp.locked','mp.bypass'));s=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'manually played'):self.play(g,'mp.bypass')
        self.assertEqual(g.snapshot(),s)

    def test_pending_creation_restores_replays_and_failed_selection_rolls_back(self):
        g=self.game(hand=('mp.waitcreate',));self.play(g,'mp.waitcreate');s=self.portable(g)
        choice=g.state.pending_choice
        with self.assertRaisesRegex(ResolutionError,'Diagnostic continuation failure'):
            g.apply(SelectChoice(1,choice.id,('fail',)))
        self.assertEqual(g.snapshot(),s)
        g.apply(SelectChoice(1,choice.id,('create',)));self.blocked(g,self.card(g))
        restored=Game.from_snapshot(s,registry());restored.apply(SelectChoice(1,choice.id,('create',)))
        self.assertEqual(restored.snapshot(),g.snapshot());self.portable(g)

    def test_player_command_rejection_is_opaque_and_enemy_hand_identity_stays_private(self):
        g=self.game();port=g.for_player(1);view=port.observe();eid=self.card(g);s=g.snapshot()
        ref=view['observation']['players'][0]['hand'][0]['ref']
        self.assertFalse(any(a.get('card')==ref and a['type']=='play_card' for a in port.legal_actions()['actions']))
        reply=port.submit({'revision':view['revision'],'action':{'type':'play_card','card':ref}})
        self.assertFalse(reply['accepted']);self.assertEqual(reply['error'],'invalid_action');self.assertEqual(g.snapshot(),s)
        other=self.game(hand=('mp.open',))
        self.assertEqual(g.for_player(2).observe(),other.for_player(2).observe())
        self.assertEqual(g.for_player(2).events(),other.for_player(2).events())

    def test_full_original_payment_proof_binds_manual_permission(self):
        g=self.game(permit=True);g._state.action_number=1  # Trusted accepted root before payment.
        r=Resolution(g);source=r.state.entities[self.card(g)];quote=quote_cost(r.state,r.registry,source)
        prepared=prepare_play(r.state,r.registry,source,None,quote)
        _,proof=capture_hand_cost_proof(r,prepared,quote)
        validate_hand_cost_proof(proof,r.registry)
        with self.assertRaisesRegex(ValueError,'original manual play permission'):
            validate_hand_cost_proof(proof,registry())

    def test_compact_paid_spell_and_nonspell_history_binds_original_permission(self):
        for name in ('mp.locked','mp.minion'):
            g=self.game(hand=(name,),permit=True);self.play(g,name);play=g.state.play_history[-1]
            validate_compact_hand_costs(g.state,g.registry,play)
            with self.assertRaisesRegex(ValueError,'original manual play permission'):
                validate_compact_hand_costs(g.state,registry(),play)
            self.portable(g,permit=True)

    def test_permission_is_registered_identity_and_wrong_registry_or_old_schema_is_rejected(self):
        self.assertNotEqual(registry().fingerprint(),registry(True).fingerprint())
        g=self.game();s=g.snapshot()
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry(True))
        for old in (1,231):
            bad={**s,'schema_version':old}
            with self.assertRaisesRegex(SnapshotError,'Unsupported snapshot schema'):
                Game.from_snapshot(bad,registry())


if __name__=='__main__':unittest.main()
