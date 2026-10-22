"""Real Isiset entry and native Freeze's original spell-Mana/lifecycle boundaries."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest

from hs_sim.cards.isiset_card import CARD,TOKEN,load_batch,register_isiset_card
from hs_sim.engine import (BattlecryRepeatSpec,CardDefinition,CardType,EndTurn,Game,
    PlayCard,PlayerSetup,Registry,Scenario,SelectChoice,SnapshotError,TriggerSpec)
from hs_sim.engine.effects import (AddCostModifier,ChangeControl,ChoiceOption,CopyMinion,
    Destroy,Freeze,GrantKeyword,InvokeBehavior,RequestChoice,ReturnToHand,
    Silence,SpendMana,Summon,Transform,Unfreeze)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import (CardClass,CardMetadata,CostSpec,Keyword,KeywordAuraSpec,
    PaymentType,Rarity,TargetSpec,Zone)
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.spell_mana_freeze import BIRTH,PROGRESS,RELEASE,SpellManaFreezeProfile
from tools.card_batch import check_face

P='fixture.isiset.'
HERO,UNIT,SIX,NINE,FIFTEEN,ZERO,CONSUME,AUTO,HEALTH_MOD,BIG,REPEAT,WARD,WATCH=(P+x for x in
    ('hero','unit','six','nine','fifteen','zero','consume','auto','health-mod','big','repeat','ward','watch'))
META=CardMetadata(True,(CardClass.MAGE,),Rarity.COMMON,tribes=())


@lru_cache(maxsize=None)
def registry(mode='normal',role='writer'):
    assert role in ('writer','reader')
    r=Registry('isiset-'+mode);register_isiset_card(r)
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,
        metadata=CardMetadata(False,(CardClass.MAGE,),Rarity.NONE,tribes=())))
    for cid,cost in ((UNIT,0),(BIG,15)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=1,health=3,metadata=META))
    r.register_card(CardDefinition(REPEAT,REPEAT,CardType.MINION,health=3,metadata=META,
        battlecry_repeats=(BattlecryRepeatSpec(),)))
    r.register_card(CardDefinition(WARD,WARD,CardType.MINION,health=3,metadata=META,
        keyword_auras=(KeywordAuraSpec(Keyword.CANT_BE_FROZEN,target='friendly_minions',include_self=True),)))
    r.register_behavior(P+'noop',lambda c:())
    for cid,cost in ((SIX,6),(NINE,9),(FIFTEEN,15),(ZERO,0)):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=P+'noop',metadata=META))
    r.register_behavior(CONSUME,lambda c:(SpendMana(c.player_id,9,c.source_id),))
    r.register_card(CardDefinition(CONSUME,CONSUME,CardType.SPELL,cost=6,on_play=CONSUME,metadata=META))
    r.register_behavior(AUTO,lambda c:(CastSpell(c.player_id,FIFTEEN,c.source_id),))
    r.register_card(CardDefinition(AUTO,AUTO,CardType.SPELL,on_play=AUTO,metadata=META))
    r.register_behavior(HEALTH_MOD,lambda c:(AddCostModifier(c.player_id,
        CostSpec(payment=PaymentType.HEALTH,card_types=(CardType.SPELL,))),))
    r.register_card(CardDefinition(HEALTH_MOD,HEALTH_MOD,CardType.MINION,health=1,battlecry=HEALTH_MOD,metadata=META))
    operations={
        'freeze':lambda c:(Freeze(c.target_id,c.source_id),),
        'unfreeze':lambda c:(Unfreeze(c.target_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'transform-native':lambda c:(Transform(c.target_id,TOKEN),),
        'transform-plain':lambda c:(Transform(c.target_id,UNIT),),
        'control':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'reborn':lambda c:(GrantKeyword(c.target_id,Keyword.REBORN),),
        'dormant':lambda c:(MakeDormant(c.target_id,1,c.source_id),),
        'summon-native':lambda c:(Summon(c.player_id,TOKEN),),
        'summon-root':lambda c:(Summon(c.player_id,CARD),),
    }
    for key,body in operations.items():
        cid=P+key;r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META,
            targeting=None if key.startswith('summon-')else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    def fail(c):raise ResolutionError('Deliberate conditional Freeze reaction failure')
    r.register_behavior(P+'fail',fail)
    if mode!='normal':
        event='minion_summoned'if mode=='entry-wait'else 'card_committed'if mode=='counter'else 'unfrozen'
        def watch(c):
            if mode=='counter':
                return (CounterSpell(dict(c.event.data)['window_id']),)if c.event.player_id!=c.player_id else ()
            if mode=='entry-wait':
                if c.event.target_id is None or c.state.entities[c.event.target_id].card_id!=TOKEN:return ()
            elif dict(c.event.data).get('reason')!='spell_mana':return ()
            if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            return (RequestChoice(3-c.player_id,(ChoiceOption('ok','Continue'),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior(WATCH,watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=3,metadata=META,
            triggers=(TriggerSpec(event,WATCH),)))
    r.validate();r.freeze();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events'])
    s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')})
    return s


class IsisetTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy_hand=(),enemy_board=(),mode='normal'):
        self.mode=mode
        if mode=='counter':enemy_board=(*enemy_board,WATCH)
        elif mode!='normal':board=(*board,WATCH)
        return Game.from_scenario(Scenario(tuple(PlayerSetup(HERO,hand=hand if p==1 else enemy_hand,
            board=board if p==1 else enemy_board,deck=(UNIT,)*16,mana=50,max_mana=50,mana_cap=50)
            for p in (1,2)),seed=386),registry(mode))
    def play(self,g,cid=CARD,target=None):
        pid=g.state.active_player
        e=next(g.state.entities[i]for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,e.id,target_id=target,position=len(g.state.players[pid].board)if e.kind==CardType.MINION else None));return e.id
    def tokens(self,g,pid=1):return [g.state.entities[i]for i in g.state.players[pid].board if g.state.entities[i].card_id==TOKEN]
    def token(self,g,pid=1):return self.tokens(g,pid)[0]
    def remaining(self,g,pid=1):return self.token(g,pid).spell_mana_freeze.remaining
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def select(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        reader=registry(self.mode,'reader');self.assertIsNot(reader,g.registry)
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,reader)
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);return other

    def test_complete_fixed_rows_root_faces_and_explicit_unconfirmed_dependency_link(self):
        pack=load_batch();root=pack['cards'][0]['record'];token=pack['dependencies'][0]['record']
        self.assertEqual((root['id'],token['id'],token['name'],token['collectible']),(CARD,TOKEN,'冰寒巨人守护者',False))
        self.assertEqual(pack['official_faces_verified'],2)
        self.assertFalse(pack['source_limits']['BE_254_primary_face_verified'])
        self.assertFalse(pack['source_limits']['dependency_assignment_primary_confirmed'])
        for face in pack['official_observations']:check_face(root,face['face'],face['locale'])
        self.assertEqual(registry().spell_mana_freeze_profiles[TOKEN],SpellManaFreezeProfile(TOKEN,15))

    def test_actual_battlecry_pays_six_and_summons_two_native_ten_tens(self):
        g=self.game((CARD,));source=self.play(g)
        self.assertEqual(g.state.players[1].mana,44);self.assertEqual(len(self.tokens(g)),2)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(5,5))
        for e in self.tokens(g):
            self.assertEqual((e.attack,e.health,e.spell_mana_freeze.remaining),(10,10,15));self.assertTrue(e.frozen)
        self.assertEqual(len({e.spell_mana_freeze.id for e in self.tokens(g)}),2);self.portable(g)

    def test_two_fixed_summon_requests_respect_capacity_and_battlecry_repeat(self):
        for n,expected in ((4,2),(5,1),(6,0)):
            g=self.game((CARD,),board=(UNIT,)*n);self.play(g);self.assertEqual(len(self.tokens(g)),expected)
        g=self.game((CARD,),board=(REPEAT,));self.play(g);self.assertEqual(len(self.tokens(g)),4)

    def test_natural_root_summon_has_no_battlecry_and_native_body_always_has_gate(self):
        g=self.game((P+'summon-root',P+'summon-native'));self.play(g,P+'summon-root')
        self.assertFalse(self.tokens(g));self.play(g,P+'summon-native')
        self.assertTrue(self.token(g).frozen);self.assertEqual(self.remaining(g),15)

    def test_normal_turn_thaw_does_not_release_native_gate(self):
        g=self.game(board=(TOKEN,))
        for _ in range(3):self.cycle(g);self.assertTrue(self.token(g).frozen)
        self.assertEqual(self.remaining(g),15);self.portable(g)

    def test_original_six_plus_nine_payments_release_before_spell_payload(self):
        g=self.game((SIX,NINE),board=(TOKEN,));self.play(g,SIX)
        self.assertEqual(self.remaining(g),9);self.assertTrue(self.token(g).frozen)
        self.play(g,NINE);self.assertEqual(self.remaining(g),0);self.assertFalse(self.token(g).frozen)
        self.assertEqual(self.token(g).spell_mana_freeze.released_reason,'mana');self.portable(g)

    def test_paid_spell_plus_explicit_spell_sourced_consumption_counts_actual_mana(self):
        g=self.game((CONSUME,),board=(TOKEN,));self.play(g,CONSUME)
        self.assertFalse(self.token(g).frozen);self.assertEqual(g.state.players[1].mana,35)
        self.assertEqual([(x.kind,x.amount)for x in self.token(g).spell_mana_freeze.steps],[('play',6),('consume',9)])
        self.portable(g)

    def test_zero_minion_and_free_automatic_cast_are_not_spell_mana(self):
        g=self.game((ZERO,BIG,AUTO),board=(TOKEN,))
        for card in (ZERO,BIG,AUTO):self.play(g,card)
        self.assertEqual(self.remaining(g),15);self.assertTrue(self.token(g).frozen)
        self.assertEqual(sum(x.amount for x in self.token(g).spell_mana_freeze.steps),0);self.portable(g)

    def test_health_paid_spell_does_not_credit_nominal_fifteen_cost(self):
        g=self.game((HEALTH_MOD,FIFTEEN),board=(TOKEN,));self.play(g,HEALTH_MOD);self.play(g,FIFTEEN)
        self.assertEqual(self.remaining(g),15);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,15)

    def test_countered_real_paid_spell_still_counts_its_committed_mana(self):
        g=self.game((FIFTEEN,),board=(TOKEN,),mode='counter');self.play(g,FIFTEEN)
        self.assertFalse(self.token(g).frozen);self.assertTrue(g.state.play_history[-1].countered)
        self.portable(g)

    def test_entry_baseline_excludes_old_payments_and_independent_new_bodies_start_fresh(self):
        g=self.game((FIFTEEN,P+'summon-native',SIX,P+'summon-native'))
        self.play(g,FIFTEEN);self.play(g,P+'summon-native');self.play(g,SIX);self.play(g,P+'summon-native')
        self.assertEqual([e.spell_mana_freeze.remaining for e in self.tokens(g)],[9,15]);self.portable(g)

    def test_current_controller_progress_preserves_residence_without_retroactive_credit(self):
        g=self.game((SIX,P+'control'),board=(TOKEN,),enemy_hand=(SIX,NINE));target=self.token(g).id
        self.play(g,SIX);old=self.token(g).spell_mana_freeze;self.play(g,P+'control',target)
        g.apply(EndTurn(1));self.play(g,SIX);self.assertEqual(self.remaining(g,2),3)
        self.play(g,NINE);current=self.token(g,2).spell_mana_freeze
        self.assertEqual(current.origin,old.origin);self.assertFalse(self.token(g,2).frozen);self.portable(g)

    def test_opponent_payments_are_recorded_as_zero_until_the_body_changes_controller(self):
        g=self.game(board=(TOKEN,),enemy_hand=(FIFTEEN,));g.apply(EndTurn(1));self.play(g,FIFTEEN)
        self.assertEqual(self.remaining(g),15);self.assertEqual(self.token(g).spell_mana_freeze.steps[-1].amount,0)
        self.portable(g)

    def test_silence_and_manual_unfreeze_close_gate_and_later_freeze_is_ordinary(self):
        for operation,reason in (('silence','silence'),('unfreeze','unfreeze')):
            g=self.game((P+operation,P+'freeze'),board=(TOKEN,));target=self.token(g).id
            self.play(g,P+operation,target);self.assertFalse(self.token(g).frozen)
            self.assertEqual(self.token(g).spell_mana_freeze.released_reason,reason)
            self.play(g,P+'freeze',target);self.assertTrue(self.token(g).frozen);self.cycle(g)
            self.assertFalse(self.token(g).frozen);self.portable(g)

    def test_cannot_be_frozen_aura_releases_native_gate_without_rearming_on_source_death(self):
        g=self.game((WARD,P+'kill',P+'freeze'),board=(TOKEN,));target=self.token(g).id
        ward=self.play(g,WARD);self.assertFalse(self.token(g).frozen)
        self.assertEqual(self.token(g).spell_mana_freeze.released_reason,'cannot_be_frozen')
        self.play(g,P+'kill',ward);self.play(g,P+'freeze',target);self.cycle(g)
        self.assertFalse(self.token(g).frozen);self.portable(g)

    def test_partial_progress_copy_has_fresh_printed_gate(self):
        g=self.game((SIX,P+'copy'),board=(TOKEN,));self.play(g,SIX);old=self.token(g)
        self.play(g,P+'copy',old.id)
        self.assertEqual([e.spell_mana_freeze.remaining for e in self.tokens(g)],[9,15]);self.portable(g)

    def test_return_to_hand_and_real_reentry_allocate_fresh_gate(self):
        g=self.game((SIX,P+'bounce'),board=(TOKEN,));self.play(g,SIX);old=self.token(g)
        self.play(g,P+'bounce',old.id);self.assertIsNone(g.state.entities[old.id].spell_mana_freeze)
        self.play(g,TOKEN);new=self.token(g).spell_mana_freeze
        self.assertEqual(new.remaining,15);self.assertNotEqual(new.id,old.spell_mana_freeze.id);self.portable(g)

    def test_transform_to_and_from_native_uses_actual_current_printed_profile(self):
        g=self.game((P+'transform-native',SIX,P+'transform-plain'),board=(UNIT,));target=g.state.players[1].board[0]
        self.play(g,P+'transform-native',target);self.assertEqual(self.remaining(g),15)
        self.play(g,SIX);self.play(g,P+'transform-plain',target)
        self.assertIsNone(g.state.entities[target].spell_mana_freeze);self.assertFalse(g.state.entities[target].frozen);self.portable(g)

    def test_reborn_uses_fresh_native_gate_and_does_not_inherit_paid_prefix(self):
        g=self.game((SIX,P+'reborn',P+'kill'),board=(TOKEN,));target=self.token(g).id
        self.play(g,SIX);self.play(g,P+'reborn',target);self.play(g,P+'kill',target)
        new=self.token(g);self.assertNotEqual(new.id,target);self.assertEqual(new.health,1)
        self.assertEqual(new.spell_mana_freeze.remaining,15);self.assertTrue(new.frozen);self.portable(g)

    def test_dormant_residence_keeps_original_budget_and_credits_controller_payment(self):
        g=self.game((P+'dormant',FIFTEEN),board=(TOKEN,));target=self.token(g).id
        self.play(g,P+'dormant',target);self.assertIsNotNone(self.token(g).dormancy)
        self.play(g,FIFTEEN);self.assertFalse(self.token(g).frozen);self.cycle(g)
        self.assertIsNone(self.token(g).dormancy);self.assertFalse(self.token(g).frozen);self.portable(g)

    def test_source_death_does_not_own_summoned_native_gate(self):
        g=self.game((CARD,P+'kill',SIX));source=self.play(g);self.play(g,P+'kill',source);self.play(g,SIX)
        self.assertEqual([e.spell_mana_freeze.remaining for e in self.tokens(g)],[9,9]);self.portable(g)

    def test_actual_entry_wait_restores_pending_second_summon(self):
        g=self.game((CARD,),mode='entry-wait');self.play(g);self.assertEqual(len(self.tokens(g)),1)
        other=self.portable(g)
        for match in (g,other):
            while match.state.pending_choice:self.select(match)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.tokens(g)),2)

    def test_actual_payment_thaw_wait_restores_without_double_credit_or_payment(self):
        g=self.game((FIFTEEN,),board=(TOKEN,),mode='thaw-wait');self.play(g,FIFTEEN)
        self.assertFalse(self.token(g).frozen);self.assertEqual(g.state.players[1].mana,35)
        other=self.portable(g)
        for match in (g,other):self.select(match)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.remaining(g),0)

    def test_payment_reaction_failure_rolls_back_original_spell_mana_and_gate(self):
        g=self.game((FIFTEEN,),board=(TOKEN,),mode='fail');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,FIFTEEN)
        self.assertEqual(g.snapshot(),before)

    def test_late_choice_failure_preserves_already_accepted_payment_and_gate(self):
        g=self.game((FIFTEEN,),board=(TOKEN,),mode='thaw-wait');self.play(g,FIFTEEN);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.select(g,'fail')
        self.assertEqual(g.snapshot(),before);self.select(g);self.assertEqual(self.remaining(g),0)

    def test_rehashed_save_cannot_drop_binding_payment_prefix_or_private_original_witnesses(self):
        g=self.game((SIX,),board=(TOKEN,));self.play(g,SIX);target=self.token(g).id;saved=g.snapshot()
        def binding(s):return s['state']['entities'][str(target)]['spell_mana_freeze']
        mutations=(lambda s:s['state']['entities'][str(target)].update(spell_mana_freeze=None),
            lambda s:binding(s).update(amount=16),lambda s:binding(s)['steps'][0].update(amount=5),
            lambda s:binding(s).update(steps=[]),
            lambda s:s.update(events=[e for e in s['events']if e['kind']!=BIRTH]),
            lambda s:s.update(events=[e for e in s['events']if e['kind']!=PROGRESS]))
        for mutate in mutations:
            bad=deepcopy(saved);mutate(bad)
            with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry(self.mode,'reader'))
        self.portable(g)

    def test_player_projection_and_opaque_choice_hide_native_proofs_and_payment_cursors(self):
        g=self.game((FIFTEEN,),board=(TOKEN,),mode='thaw-wait');self.play(g,FIFTEEN)
        for pid in (1,2):
            visible=json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for key in (BIRTH,PROGRESS,RELEASE,'spell_mana_freeze','start_play_id','start_consumption_id','steps','rng_state'):
                self.assertNotIn('"'+key+'"',visible)
        port=g.for_player(2);commands=port.legal_actions()
        command=next(x for x in commands['actions']if x['type']=='select_choice')
        port.submit({'revision':commands['revision'],'action':command});self.assertFalse(self.token(g).frozen)


if __name__=='__main__':unittest.main()
