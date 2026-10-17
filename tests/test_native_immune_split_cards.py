"""Native Bone Flurry, explicit SPELL bonus policy and real split boundaries."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_immune_split_cards import FLURRY,load_batch
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,
    PlayerEffectSpec,PlayerSetup,Scenario,SelectChoice,SnapshotError,TargetSpec,Zone)
from hs_sim.engine.effects import (ChoiceOption,Damage,Destroy,InvokeBehavior,RequestChoice,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import DamageKind,HealthFlow,HealthLayer,HealthOp,HealthRule,LimitedTriggerSpec,RewindSpec
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.random_split_damage import (FinishRandomSplitRoot,NON_SPELL_PROFILE,
    RandomSplitDamage,SplitDamageScope,quote_budget)
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash,SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.targets import canonical_digest

TEST='k137.';YETI='CORE_CS2_182'


def registry(mode=None):
    r=build_registry()
    r.register_card(CardDefinition(TEST+'power','Spell bonus provider',CardType.MINION,health=20,spell_damage=5))
    r.register_card(CardDefinition(TEST+'body','Later real target',CardType.MINION,health=20))
    r.register_card(CardDefinition(TEST+'scale','Per-packet source modifier',CardType.MINION,health=20,
        health_rules=(HealthRule(HealthFlow.DAMAGE,HealthOp.SCALE,2,layer=HealthLayer.SOURCE,source_relation='friendly'),)))
    r.register_player_effect(PlayerEffectSpec(TEST+'persistent',TEST+'persistent',spell_damage=2))
    def fail(c):raise ResolutionError('K137 deliberate continuation failure')
    bodies=dict(kill=lambda c:(Destroy(c.target_id,c.source_id),),
        enemy_cast=lambda c:(CastSpell(2,FLURRY,c.source_id),),
        rewind=lambda c:(CastSpell(c.player_id,FLURRY,c.source_id),),
        wound_hero=lambda c:(Damage(c.state.players[2].hero_id,29,c.source_id,DamageKind.SPELL),),
        persistent=lambda c:(AddPlayerEffect(c.player_id,TEST+'persistent',c.source_id),),
        ordinary=lambda c:(RandomSplitDamage(c.player_id,c.cast.id,c.source_id,3),),
        immune=lambda c:(RandomSplitDamage(c.player_id,c.cast.id,c.source_id,3,spell_bonus_multiplier=0),),
        fail=fail)
    for name,body in bodies.items():
        r.register_behavior(TEST+name,body)
        if name=='fail':continue
        kwargs=dict(targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)))if name=='kill'else{}
        if name=='rewind':kwargs.update(keywords=(Keyword.REWIND,),rewind=RewindSpec())
        r.register_card(CardDefinition(TEST+name,name,CardType.SPELL,on_play=TEST+name,**kwargs))
    if mode:
        def eligible(c):
            v=health_result(c.event)
            return v is not None and v.split_packet is not None and v.split_packet.index==(3 if mode=='last'else 1)and v.source_card_id==FLURRY
        def watch(c):
            if mode=='death':return (Destroy(c.source_id,c.event.source_id),)
            provider=next((i for i in c.state.players[1].board if c.state.entities[i].card_id==TEST+'power'),None)
            options=[ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',(
                InvokeBehavior(TEST+'fail',c.source_id,c.player_id),)),
                ChoiceOption('sacrifice','Actual friendly death',(Destroy(c.source_id,c.event.source_id),)),
                ChoiceOption('spawn','New actual enemy target',(Summon(2,TEST+'body'),))]
            if provider is not None:options.append(ChoiceOption('remove_bonus','Remove unused bonus',(Destroy(provider,c.source_id),)))
            return (RequestChoice(c.player_id,tuple(options),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible)
        r.register_card(CardDefinition(TEST+'watch','First real packet witness',CardType.MINION,health=20,
            limited_triggers=(LimitedTriggerSpec('health_resolved',TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r


@lru_cache(maxsize=None)
def shared(mode):return registry(mode)


class NativeImmuneSplitTests(unittest.TestCase):
    def game(self,hand=(FLURRY,),board=(),enemy=(),mode=None):
        self.mode=mode
        if mode:board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,
            mana=40,max_mana=40,mana_cap=40),PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,
            mana=40,max_mana=40,mana_cap=40)),seed=137),shared(mode))
    def eid(self,g,cid,p=1,zone='board'):
        return next(i for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid=FLURRY,target=None):
        i=self.eid(g,cid,zone='hand');g.apply(PlayCard(1,i,target));return i
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def rows(self,g):return [root for root in g.state.split_damage_history if root.quote.source.card_id==FLURRY]
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(self.mode))
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry(self.mode)).snapshot(),s);return other
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError)as error:Game.from_snapshot(s,shared(self.mode))
        self.assertNotIn('digest mismatch',str(error.exception))

    def test_complete_original_immune_tag_runes_and_unschooled_native_spell(self):
        d=load_batch();row,=d['cards'];raw=row['record'];card=shared(None).card(FLURRY)
        self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(card.metadata,metadata_from_record(raw))
        self.assertEqual((card.cost,card.spell_school,card.metadata.runes.unholy),(2,None,1))
        self.assertEqual(raw['tags']['349'],1);self.assertEqual(len(d['official_observations']),2)
        self.assertFalse(d['formal_pool_complete']or d['cn_calibrated'])

    def test_real_spell_ignores_all_five_spell_bonus_and_keeps_three_spell_units(self):
        g=self.game(board=(TEST+'power',));source=self.play(g);root,=self.rows(g)
        self.assertEqual((root.request.spell_bonus_multiplier,root.quote.spell_bonus,root.quote.budget),(0,0,3))
        self.assertEqual(root.quote.contributions,());self.assertEqual(len(root.packets),3)
        self.assertEqual((root.request.source_id,root.quote.cast.source_id),(source,source))
        results=[r.health_result for r in g.state.damage_history]
        self.assertTrue(all((v.base_amount,v.spell_bonus,v.damage_kind)==(1,0,'spell')for v in results))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,27);self.assertEqual(g.state.players[1].mana,38)

    def test_existing_friendly_death_gives_two_independent_roots_on_one_paid_cast(self):
        g=self.game((TEST+'kill',FLURRY),board=(YETI,TEST+'power'));self.play(g,TEST+'kill',self.eid(g,YETI));self.play(g)
        roots=self.rows(g);self.assertEqual(len(roots),2);self.assertEqual([r.quote.budget for r in roots],[3,3])
        self.assertEqual(len({r.request.cast_id for r in roots}),1);self.assertTrue(all(r.parent_id is None for r in roots))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,24);self.assertEqual(g.state.players[1].mana,38)
        self.portable(g)

    def test_enemy_death_or_previous_turn_friendly_death_does_not_unlock_extra_wave(self):
        g=self.game((TEST+'kill',FLURRY),enemy=(YETI,));self.play(g,TEST+'kill',self.eid(g,YETI,2));self.play(g)
        self.assertEqual(len(self.rows(g)),1)
        g=self.game((TEST+'kill',FLURRY),board=(YETI,));self.play(g,TEST+'kill',self.eid(g,YETI))
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g);self.assertEqual(len(self.rows(g)),1)

    def test_first_wave_actual_friendly_death_is_seen_by_fresh_extra_condition(self):
        g=self.game(mode='death');source=self.eid(g,TEST+'watch');self.play(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(len(self.rows(g)),2)
        self.assertEqual(sum(len(r.packets)for r in self.rows(g)),6)

    def test_last_first_wave_packet_wait_restore_failure_and_death_enables_extra_once(self):
        g=self.game(mode='last');self.play(g);self.assertEqual(len(self.rows(g)[0].packets),3)
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for x in(g,other):self.choose(x,'sacrifice')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.rows(g)),2)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,24)

    def test_first_packet_wait_does_not_redraw_and_removed_bonus_never_changes_immune_budget(self):
        g=self.game(board=(TEST+'power',),mode='wait');self.play(g);root,=self.rows(g)
        first=root.packets[0].selection;other=self.portable(g)
        for x in(g,other):self.choose(x,'remove_bonus')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.rows(g)[0].packets[0].selection,first)
        self.assertEqual([r.quote.budget for r in self.rows(g)],[3,3])

    def test_later_packets_requery_actual_targets_instead_of_reusing_first_pool(self):
        g=self.game(mode='wait');self.play(g);first=self.rows(g)[0].packets[0].selection
        self.choose(g,'spawn');i=self.eid(g,TEST+'body',2);root,=self.rows(g)
        self.assertNotIn(i,[c.allocation.entity_id for c in first.candidates])
        self.assertTrue(all(i in[c.allocation.entity_id for c in p.selection.candidates]for p in root.packets[1:]))

    def test_out_of_turn_actual_caster_uses_its_own_current_global_turn_deaths(self):
        g=self.game((TEST+'kill',TEST+'enemy_cast'),enemy=(YETI,));self.play(g,TEST+'kill',self.eid(g,YETI,2));self.play(g,TEST+'enemy_cast')
        self.assertEqual(len(self.rows(g)),2);self.assertTrue(all(r.request.player_id==2 for r in self.rows(g)))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,24)

    def test_terminal_first_unit_interrupts_remaining_budget_and_conditional_tail(self):
        g=self.game((TEST+'wound_hero',FLURRY));self.play(g,TEST+'wound_hero');self.play(g);root,=self.rows(g)
        self.assertEqual(g.state.status,'finished');self.assertEqual(len(root.packets),1);self.assertTrue(root.interrupted)
        self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_default_ordinary_split_still_gets_spell_bonus_and_zero_policy_retains_other_damage_rules(self):
        g=self.game((TEST+'ordinary',),board=(TEST+'power',));self.play(g,TEST+'ordinary');root,=g.state.split_damage_history
        self.assertEqual((root.request.spell_bonus_multiplier,root.quote.spell_bonus,root.quote.budget),(1,5,8))
        g=self.game(board=(TEST+'power',TEST+'scale'));self.play(g);root,=self.rows(g)
        self.assertEqual(root.quote.budget,3);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,24)
        self.assertTrue(all(r.health_result.modified_amount==2 for r in g.state.damage_history))

    def test_persistent_player_spell_bonus_is_ignored_only_by_immune_request(self):
        g=self.game((TEST+'persistent',FLURRY,TEST+'ordinary'));self.play(g,TEST+'persistent');self.play(g)
        self.assertEqual(self.rows(g)[0].quote.contributions,());self.play(g,TEST+'ordinary')
        self.assertEqual((g.state.split_damage_history[-1].quote.spell_bonus,g.state.split_damage_history[-1].quote.budget),(2,5))

    def test_native_rewind_retains_diagnostic_roots_but_only_final_immune_state(self):
        g=self.game((TEST+'rewind',),board=(TEST+'power',));self.play(g,TEST+'rewind');self.portable(g);self.choose(g,'retry')
        self.assertEqual(len(self.rows(g)),1);self.assertEqual(self.rows(g)[0].quote.budget,3)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,27);self.portable(g)

    def test_immune_request_cannot_borrow_positive_spell_contributions(self):
        g=self.game(board=(TEST+'power',),mode='wait');self.play(g);root,=self.rows(g)
        tail=next(w for w in g._frame.continuation if type(w)is FinishRandomSplitRoot)
        ordinary=quote_budget(tail.proof.state,g.registry,replace(root.request,spell_bonus_multiplier=1),root.quote.root_action,root.quote.event_cursor)
        self.assertEqual(ordinary.spell_bonus,5)
        with self.assertRaisesRegex(ValueError,'Immune split budget'):replace(root,quote=ordinary)

    def test_waiting_request_invalid_missing_or_rewritten_numeric_policy_rejects_after_rehash(self):
        g=self.game(board=(TEST+'power',),mode='wait');self.play(g)
        for mutation in('invalid','missing','ordinary'):
            with self.subTest(mutation=mutation):
                s=deepcopy(g.snapshot());request=s['state']['split_damage_history'][0]['request']
                if mutation=='missing':request.pop('spell_bonus_multiplier')
                else:request['spell_bonus_multiplier']=2 if mutation=='invalid'else 1
                self.reject(s)

    def test_numeric_policy_is_strict_and_cannot_be_given_to_non_spell_profile(self):
        for value in(True,-1,2,'0'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):RandomSplitDamage(1,1,1,3,spell_bonus_multiplier=value)
        with self.assertRaises(ValueError):RandomSplitDamage(1,None,1,3,profile=NON_SPELL_PROFILE,
            kind=DamageKind.MINION_ABILITY,spell_bonus_multiplier=0)

    def test_player_projection_has_public_damage_without_private_split_policy_proofs(self):
        g=self.game(board=(TEST+'power',),mode='wait');self.play(g)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('spell_bonus_multiplier','contributions','split_packet','rng_before','rng_after','resolution_frame'):
                self.assertNotIn('"'+key+'"',public)

    def test_old_schema_requires_original_engine_and_all_old_full_definitions_are_unchanged(self):
        g=self.game();s=g.snapshot();s['schema_version']=344
        with self.assertRaisesRegex(SnapshotError,f'schemas 1 through {SNAPSHOT_SCHEMA_VERSION-1}'):Game.from_snapshot(s,shared(None))
        with patch('hs_sim.cards.native_immune_split_cards.register_native_immune_split_cards',lambda r:None):before=build_registry()
        after=build_registry();self.assertEqual(set(after.cards)-set(before.cards),{FLURRY})
        for cid,c in before.cards.items():self.assertEqual(asdict(c),asdict(after.card(cid)))
        self.assertEqual(dict(before.pool_cards),dict(after.pool_cards));self.assertEqual(dict(before.pools),dict(after.pools))
        self.assertEqual(dict(before.generation_families),dict(after.generation_families))


if __name__=='__main__':unittest.main()
