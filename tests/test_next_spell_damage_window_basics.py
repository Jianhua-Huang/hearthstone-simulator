"""Pending Spell Damage belongs to one accepted physical payload, not the player."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest
from hs_sim.engine import (CardDefinition,CardType,CastWhenDrawnSpec,EndTurn,Game,Keyword,PlayCard,RandomSplitDamage,
    PlayerEffectSpec,PlayerSetup,Registry,ResolutionError,Scenario,SelectChoice,SnapshotError,TargetSpec,Zone)
from hs_sim.engine.effects import (ChoiceOption,Damage,DamageKind,Destroy,Draw,GainArmor,
    InvokeBehavior,RequestChoice,Silence)
from hs_sim.engine.health_rules import spell_bonus
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

ROOT=Path(__file__).resolve().parents[1]
PIN='25aa17ed7158f99b99e9d34b153a6f287d1f9be63c41f06d911d0fb07ab7ff06'
ARC='BAR_064'; BOOST='spell.next.damage.two'
def evidence():
    p=json.loads((ROOT/'data/support/next-spell-damage-window-basics.json').read_bytes())
    if canonical_digest(p)!=PIN: raise ValueError('Next physical spell raw changed')
    return p
def registry():
    r=Registry('isolated-next-physical-spell-damage-v1'); raw=next(x for x in evidence()['records'] if x['id']==ARC)
    r.register_card(CardDefinition('hero','Diagnostic hero',CardType.HERO,health=80,metadata=metadata()))
    r.register_card(CardDefinition('plain','Diagnostic minion',CardType.MINION,health=20,metadata=metadata()))
    r.register_behavior('activate',lambda c:(AddPlayerEffect(c.player_id,BOOST,c.source_id),))
    r.register_card(CardDefinition(ARC,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],battlecry='activate',metadata=metadata_from_record(raw)))
    r.register_player_effect(PlayerEffectSpec(BOOST,ARC,kind='next_spell_damage',spell_damage=2))
    def hit(c): return (Damage(c.state.players[2].hero_id,1,c.source_id,DamageKind.SPELL),)
    def read(c): return (GainArmor(c.player_id,spell_bonus(c.state,c.player_id,r,cast_id=c.cast.id)),)
    def fail(c): raise ResolutionError('Diagnostic scoped Spell Damage failure')
    r.register_behavior('explode',fail)
    def waiting(c): return (RequestChoice(c.player_id,(
        ChoiceOption('hit','Hit',hit(c)),ChoiceOption('fault','Fail',(InvokeBehavior('explode',c.source_id,c.player_id),)),
    ),c.source_id),)
    scripts={'spell':hit, 'twice':lambda c:(*hit(c),*hit(c)), 'read':read,
        'draw-many':lambda c:(Draw(c.player_id,1+spell_bonus(c.state,c.player_id,r,cast_id=c.cast.id)),),
        'waiting':waiting, 'auto':lambda c:(CastSpell(c.player_id,'spell',c.source_id),),
        'split':lambda c:(RandomSplitDamage(c.player_id,c.cast.id,c.source_id,1),),
        'failed-auto':lambda c:(CastSpell(c.player_id,'targeted',c.source_id),),
        'delayed':lambda c:(Damage(c.state.players[2].hero_id,1,c.state.cast_history[0].source_id,DamageKind.SPELL),),
        'fault':lambda c:(*hit(c),InvokeBehavior('explode',c.source_id,c.player_id))}
    for name,body in scripts.items():
        r.register_behavior(name,body)
        if name=='failed-auto':
            r.register_card(CardDefinition(name,'Diagnostic no-target source',CardType.MINION,health=5,battlecry=name,metadata=metadata()))
        else:
            r.register_card(CardDefinition(name,'Diagnostic '+name,CardType.SPELL,on_play=name,metadata=metadata()))
    r.register_behavior('draw-source',lambda c:(Draw(c.player_id),))
    r.register_card(CardDefinition('draw-source','Diagnostic nonspell draw',CardType.MINION,health=5,battlecry='draw-source',metadata=metadata()))
    r.register_card(CardDefinition('drawn','Diagnostic drawn spell',CardType.SPELL,on_play='spell',keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec(replacement=False),metadata=metadata()))
    r.register_card(CardDefinition('targeted','Diagnostic no enemy minion target',CardType.SPELL,on_play='spell',
        targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy'),metadata=metadata()))
    for name,body in (('destroy',lambda c:(Destroy(c.target_id,c.source_id),)),('silence',lambda c:(Silence(c.target_id),))):
        r.register_behavior(name,body); r.register_card(CardDefinition(name,name,CardType.MINION,health=5,battlecry=name,requires_target=True,metadata=metadata()))
    r.register_behavior('auto-source',lambda c:(CastSpell(c.player_id,'spell',c.source_id),))
    r.register_card(CardDefinition('auto-source','Diagnostic nonspell auto source',CardType.MINION,health=5,battlecry='auto-source',metadata=metadata()))
    return r

class NextSpellDamageWindowTests(unittest.TestCase):
    def game(self,hand=(ARC,'spell','spell'),deck=('plain',)*6):
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,deck=deck,max_mana=10,mana=10),
            PlayerSetup('hero',deck=('plain',)*6,max_mana=10,mana=10)),seed=135),registry())
    def card(self,g,name,p=1): return next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==name)
    def play(self,g,name,target=None): return g.apply(PlayCard(g.state.active_player,self.card(g,name,g.state.active_player),target))
    def health(self,g): return g.state.entities[g.state.players[2].hero_id].health
    def boost(self,g): return g.state.players[1].player_effects
    def portable(self,g):
        s=g.snapshot(); self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),registry()).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s); self.assertEqual(replay(build_replay(g),registry()).snapshot(),s); return s

    def test_four_sources_and_one_adapter_remain_explicitly_uncalibrated(self):
        p=evidence(); self.assertEqual(len(p['records']),4); self.assertFalse(p['CN_calibrated']); self.assertEqual(p['new_combinations'],0)
        self.assertEqual((registry().card(ARC).cost,registry().card(ARC).attack,registry().card(ARC).health),(2,1,3))

    def test_pending_declaration_is_positive_and_cannot_mix_effect_families(self):
        spec=registry().player_effect(BOOST)
        for kw in ({'spell_damage':0},{'spell_damage':True},{'duration':1},{'tick_event':'turn_ended'},
                {'target_policy':'spells_no_heroes'}):
            with self.subTest(kw=kw),self.assertRaises(ValueError): replace(spec,**kw)

    def test_next_manual_spell_claims_once_and_keeps_bonus_during_payload(self):
        g=self.game(); self.play(g,ARC); self.assertEqual(len(self.boost(g)),1)
        self.assertEqual(spell_bonus(g.state,1,g.registry),0)
        self.play(g,'spell'); self.assertEqual(self.health(g),77); self.assertFalse(self.boost(g))
        self.assertEqual(len(g.state.cast_history[-1].spell_damage_effects),1)
        self.play(g,'spell'); self.assertEqual(self.health(g),76); self.portable(g)

    def test_multiple_damage_steps_of_one_physical_spell_share_the_window(self):
        g=self.game(hand=(ARC,'twice')); self.play(g,ARC); self.play(g,'twice')
        self.assertEqual(self.health(g),74); self.assertEqual(len(g.state.cast_history),1); self.portable(g)

    def test_two_pending_instances_stack_only_on_the_same_next_spell(self):
        g=self.game(hand=(ARC,ARC,'spell','spell')); self.play(g,ARC); self.play(g,ARC); self.play(g,'spell')
        self.assertEqual(self.health(g),75); self.assertEqual(len(g.state.cast_history[-1].spell_damage_effects),2)
        self.play(g,'spell'); self.assertEqual(self.health(g),74); self.portable(g)

    def test_non_damage_spell_reads_cast_bonus_and_still_consumes(self):
        g=self.game(hand=(ARC,'read','spell')); self.play(g,ARC); self.play(g,'read')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2); self.assertFalse(self.boost(g))
        self.play(g,'spell'); self.assertEqual(self.health(g),79); self.portable(g)

    def test_draw_quantity_queries_cast_bonus_like_official_cram_session_requirement(self):
        g=self.game(hand=(ARC,'draw-many')); self.play(g,ARC); self.play(g,'draw-many')
        self.assertEqual(len(g.state.players[1].hand),3); self.assertFalse(self.boost(g)); self.portable(g)

    def test_cast_when_drawn_receives_and_consumes_before_next_manual_spell(self):
        g=self.game(hand=(ARC,'draw-source','spell'),deck=('drawn','plain')); self.play(g,ARC); self.play(g,'draw-source')
        self.assertEqual(self.health(g),77); self.assertEqual(g.state.cast_history[-1].origin,'draw'); self.assertFalse(self.boost(g))
        self.play(g,'spell'); self.assertEqual(self.health(g),76); self.portable(g)

    def test_effect_driven_physical_cast_also_claims_the_pending_instance(self):
        g=self.game(hand=(ARC,'auto-source','spell')); self.play(g,ARC); self.play(g,'auto-source')
        self.assertEqual(self.health(g),77); self.assertEqual(g.state.cast_history[-1].origin,'effect'); self.assertFalse(self.boost(g))
        self.play(g,'spell'); self.assertEqual(self.health(g),76); self.portable(g)

    def test_new_nested_cast_cannot_inherit_an_outer_cast_bonus(self):
        g=self.game(hand=(ARC,'auto')); self.play(g,ARC); self.play(g,'auto')
        self.assertEqual(self.health(g),79)
        self.assertEqual([len(c.spell_damage_effects) for c in g.state.cast_history],[1,0]); self.portable(g)

    def test_failed_automatic_target_retains_pending_bonus_under_local_policy(self):
        g=self.game(hand=(ARC,'failed-auto','spell')); self.play(g,ARC); self.play(g,'failed-auto')
        cast=g.state.cast_history[-1]; self.assertFalse(cast.payload_started)
        self.assertEqual(cast.spell_damage_effects,()); self.assertEqual(len(self.boost(g)),1)
        self.play(g,'spell'); self.assertEqual(self.health(g),77); self.portable(g)

    def test_whole_split_budget_uses_same_cast_window_and_restores_nested_receipt(self):
        g=self.game(hand=(ARC,'split')); self.play(g,ARC); self.play(g,'split')
        self.assertEqual(self.health(g),77)
        root=g.state.split_damage_history[-1]; self.assertEqual(root.quote.spell_bonus,2)
        self.assertEqual(len(root.quote.cast.spell_damage_effects),1); self.portable(g)

    def test_source_silence_or_death_does_not_remove_pending_player_effect(self):
        for name in ('silence','destroy'):
            with self.subTest(name=name):
                g=self.game(hand=(ARC,name,'spell')); self.play(g,ARC); self.play(g,name,g.state.players[1].board[0])
                self.assertEqual(len(self.boost(g)),1); self.play(g,'spell'); self.assertEqual(self.health(g),77); self.portable(g)

    def test_unclaimed_effect_expires_on_actual_turn_cleanup(self):
        g=self.game(); self.play(g,ARC); g.apply(EndTurn(1)); self.assertFalse(self.boost(g))
        g.apply(EndTurn(2)); self.play(g,'spell'); self.assertEqual(self.health(g),79); self.portable(g)

    def test_closed_cast_source_cannot_restore_bonus_for_delayed_effect(self):
        g=self.game(hand=(ARC,'spell','delayed')); self.play(g,ARC); self.play(g,'spell'); self.play(g,'delayed')
        self.assertEqual(self.health(g),76); self.portable(g)

    def test_waiting_cast_retains_scoped_receipt_through_restore_and_resume(self):
        g=self.game(hand=(ARC,'waiting')); self.play(g,ARC); self.play(g,'waiting'); wait=self.portable(g)
        cast=g.state.cast_history[-1]; self.assertEqual(spell_bonus(g.state,1,g.registry,cast_id=cast.id),2)
        h=Game.from_snapshot(deepcopy(wait),registry()); choice=g.state.pending_choice.id
        g.apply(SelectChoice(1,choice,('hit',))); h.apply(SelectChoice(1,choice,('hit',)))
        self.assertEqual(g.snapshot(),h.snapshot()); self.assertEqual(self.health(g),77); self.portable(g)

    def test_failed_cast_rolls_back_claim_and_failed_choice_retains_existing_claim(self):
        g=self.game(hand=(ARC,'fault','waiting')); self.play(g,ARC); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'fault')
        self.assertEqual(g.snapshot(),before); self.play(g,'waiting'); before=g.snapshot()
        with self.assertRaises(ResolutionError): g.apply(SelectChoice(1,g.state.pending_choice.id,('fault',)))
        self.assertEqual(g.snapshot(),before); self.assertFalse(self.boost(g)); self.portable(g)

    def test_cast_query_rejects_other_player_and_is_pure(self):
        g=self.game(hand=(ARC,'waiting')); self.play(g,ARC); self.play(g,'waiting'); before=g.snapshot(); cast=g.state.cast_history[-1]
        self.assertEqual(spell_bonus(g.state,1,g.registry,cast_id=cast.id),2)
        with self.assertRaises(ValueError): spell_bonus(g.state,2,g.registry,cast_id=cast.id)
        self.assertEqual(g.snapshot(),before)

    def test_tampered_claim_identity_missing_field_and_old_schema_are_rejected(self):
        g=self.game(); self.play(g,ARC); self.play(g,'spell'); snapshot=self.portable(g)
        for what in ('spec','clock','missing'):
            bad=deepcopy(snapshot); row=bad['state']['cast_history'][-1]
            if what=='spec': row['spell_damage_effects'][0]['spec_id']='unknown.bonus'
            elif what=='clock': row['spell_damage_effects'][0]['created_turn']+=1
            else: del row['spell_damage_effects']
            with self.subTest(what=what),self.assertRaises(SnapshotError): Game.from_snapshot(bad,registry())
        bad=deepcopy(snapshot); bad['schema_version']=237
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad,registry())

    def test_player_views_do_not_expose_cast_effect_receipts(self):
        g=self.game(); self.play(g,ARC); self.play(g,'spell'); before=g.snapshot()
        for p in (1,2):
            text=json.dumps(g.for_player(p).observe())
            for key in ('spell_damage_effects','source_id','entered_order'): self.assertNotIn(key,text)
        self.assertEqual(g.snapshot(),before)

if __name__=='__main__': unittest.main()
