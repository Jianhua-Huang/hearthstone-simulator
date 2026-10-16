"""Actual Husk grants: old Hero identity, true debit, one-shot display and replay."""
from copy import deepcopy
from dataclasses import asdict
import hashlib,json,unittest
from pathlib import Path

from hs_sim.cards import build_registry
from hs_sim.cards.hero_corpse_rescue_cards import BATCH_HASH,HUSK,LIFE,MARKER,load_batch,original_life_markers
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,PlayCard,
    PlayerSetup,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.actions import Concede
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,CopyMinion,Damage,DamageBatch,Destroy,
    InvokeBehavior,ReplaceHero,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind,LimitedTriggerSpec,Resource
from hs_sim.engine.registry import RuleContext,UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry as representative
from hs_sim.engine.resource_operations import HERO_PROFILE,resource_result
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest

ROOT=Path(__file__).resolve().parents[1];YETI='CORE_CS2_182';META=CardMetadata(False,(CardClass.NEUTRAL,),None)


def registry():
    r=build_registry()
    def fail(c):raise ResolutionError('K74 deliberate failure after Hero debit')
    r.register_behavior('k74.fail',fail)
    scripts=dict(fatal=lambda c:(Damage(c.state.players[c.player_id].hero_id,99,c.source_id,DamageKind.SPELL),),
        destroy_own=lambda c:(Destroy(c.state.players[c.player_id].hero_id,c.source_id),),
        destroy_enemy=lambda c:(Destroy(c.state.players[3-c.player_id].hero_id,c.source_id),),
        both=lambda c:(DamageBatch(tuple(Damage(c.state.players[p].hero_id,99,c.source_id,DamageKind.SPELL)for p in(1,2))),),
        full_batch=lambda c:(DamageBatch((Damage(c.state.players[c.player_id].hero_id,99,c.source_id,DamageKind.SPELL),
            *(Damage(i,99,c.source_id,DamageKind.SPELL)for i in c.state.players[c.player_id].board))),),
        small=lambda c:(Damage(c.state.players[c.player_id].hero_id,1,c.source_id,DamageKind.SPELL),),
        replace=lambda c:(ReplaceHero(c.player_id,'HERO_01',health=30),),
        kill=lambda c:(Destroy(c.target_id,c.source_id),),silence=lambda c:(Silence(c.target_id),),
        bounce=lambda c:(ReturnToHand(c.target_id),),give=lambda c:(ChangeControl(c.target_id,2),),
        copy=lambda c:(CopyMinion(c.target_id,c.player_id),))
    targeted={'kill','silence','bounce','give','copy'}
    for key,body in scripts.items():
        cid='k74.'+key;r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,key,CardType.SPELL,on_play=cid,requires_target=key in targeted,metadata=META))
    def wait(c):
        if c.resource_result is None or c.resource_result.profile!=HERO_PROFILE:return()
        return(RequestChoice(c.player_id,(ChoiceOption('keep','Continue',()),
            ChoiceOption('fail','Fail',(InvokeBehavior('k74.fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior('k74.wait',wait)
    r.register_card(CardDefinition('k74.wait','Resource reaction wait',CardType.MINION,health=20,
        limited_triggers=(LimitedTriggerSpec('resource_spent','k74.wait'),),metadata=META))
    r.register_card(CardDefinition('k74.breaker','Rollback observer',CardType.MINION,health=20,
        triggers=(TriggerSpec('resource_spent','k74.fail'),),metadata=META))
    r.register_card(CardDefinition('k74.block','Deathrattle prohibition fixture',CardType.MINION,health=20,
        keywords=(Keyword.DEATHRATTLE_SUPPRESSOR,),metadata=META))
    return r


def rehash(value):
    value['events_hash']=canonical_hash(value['events'])
    value['state_hash']=canonical_hash({k:v for k,v in value.items()if k not in('schema_version','events','events_hash','state_hash')})
    return value


class HeroCorpseRescueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),balance=7,enemy_hand=(),enemy_balance=11):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=30,max_mana=30,mana_cap=30,corpses=balance,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,deck=(YETI,)*8,mana=30,max_mana=30,mana_cap=30,corpses=enemy_balance,hero_power_card_id='HERO_08bp')),seed=1074),self.r)
    def entities(self,g,cid,p=1,zone='board'):
        s=g.state;return[s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid]
    def play(self,g,cid,target=None,p=1):
        eid=self.entities(g,cid,p,'hand')[0].id;g.apply(PlayCard(p,eid,target));return eid
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def bank(self,g,p=1):return g.state.players[p].resources[Resource.CORPSES]
    def markers(self,g,p=1):return[e for e in g.state.players[p].player_effects if e.spec_id==MARKER]
    def life_abilities(self,g,p=1):return[a for a in self.hero(g,p).abilities if a.kind=='deathrattle'and a.behavior_id==LIFE]
    def results(self,g):return[resource_result(e)for e in g.events if resource_result(e)is not None]
    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=g.snapshot();other=Game.from_snapshot(saved,registry());self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return other
    def both_granted(self,balance=7,other=11):
        g=self.game((HUSK,'k74.destroy_enemy','k74.both'),balance=balance,enemy_hand=(HUSK,),enemy_balance=other)
        self.play(g,HUSK);g.apply(EndTurn(1));self.play(g,HUSK,p=2);g.apply(EndTurn(2));return g

    def test_complete_raw_root_visual_records_and_real_child_not_fake_spell(self):
        data=load_batch();self.assertEqual(canonical_digest(data),BATCH_HASH)
        self.assertEqual((len(data['cards']),len(data['evidence_only'])),(1,3))
        for row in data['cards']+data['evidence_only']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual(data['evidence_only'][0]['record']['tags']['VISIBLE_PLAYER_ENCHANTMENT_CARD'],1)
        self.assertTrue(all(x['record']['id']not in self.r.cards for x in data['evidence_only']))
        c=self.r.card(HUSK);self.assertEqual((c.cost,c.attack,c.health),(4,5,3));self.assertIsNone(c.deathrattle)
        self.assertEqual(tuple(x.lower()for x in c.metadata.tribes),('undead',))
    def test_all280_engine_sources_and_old1033_definitions_remain_exact(self):
        before=ROOT/'outputs/card-integration-20261014/k74-before';old=json.loads((before/'source-guard.json').read_text(encoding='utf-8'))
        engine={k:v for k,v in old.items()if k.startswith('hs_sim/engine/')};self.assertEqual(len(engine),280)
        self.assertTrue(all(hashlib.sha256((ROOT/k).read_bytes()).hexdigest()==v for k,v in engine.items()))
        old=json.loads((before/'definition-digests.json').read_text(encoding='utf-8'));self.assertEqual(len(old),1033)
        self.assertEqual(old,{cid:canonical_digest(asdict(self.r.card(cid)))for cid in old})
        self.assertEqual(representative().fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')
    def test_actual_old_default_schema293_snapshot_still_restores_exactly(self):
        saved=json.loads((ROOT/'outputs/card-integration-20261014/k74-before/default-v65-core368-schema293.json').read_text(encoding='utf-8'))
        self.assertEqual(Game.from_snapshot(saved,representative()).snapshot(),saved)
    def test_primary_hotfix_observations_have_actual_staff_first_posts(self):
        rows=json.loads((ROOT/'outputs/card-integration-20261014/k74-official-hotfix-01/observations.json').read_text(encoding='utf-8'))
        self.assertEqual(len(rows),2)
        for row in rows:
            self.assertEqual(row['status'],200);self.assertTrue(row['staff'])
            self.assertEqual(hashlib.sha256((ROOT/row['raw']['path']).read_bytes()).hexdigest(),row['raw']['sha256'])
    def test_battlecry_installs_real_source_grant_and_public_marker(self):
        g=self.game((HUSK,));source=self.play(g,HUSK);abilities=self.life_abilities(g)
        self.assertEqual(len(abilities),1);self.assertEqual((abilities[0].source_id,abilities[0].deathrattle_grant_card_id),(source,HUSK))
        self.assertFalse(abilities[0].consumed);self.assertEqual(len(self.markers(g)),1)
        for p in(1,2):
            owner=next(x for x in g.observe(p)['players']if x['id']==1)
            self.assertEqual([x['card_id']for x in owner['player_effects']],[HUSK])
        self.portable(g)
    def test_exact_actual_caps_zero_one_partial_full_and_excess(self):
        for balance in(0,1,7,20,25):
            with self.subTest(balance=balance):
                g=self.game((HUSK,'k74.fatal'),balance=balance);self.play(g,HUSK);original=self.hero(g).id;self.play(g,'k74.fatal')
                actual=min(20,balance);self.assertEqual(self.results(g)[0].actual_amount,actual)
                self.assertEqual(self.bank(g),balance-actual);self.assertEqual(self.hero(g).id,original)
                self.assertEqual(g.state.status,'playing'if actual else'finished')
                if actual:self.assertEqual(self.hero(g).health,actual)
                self.assertFalse(self.markers(g));self.assertTrue(all(a.consumed for a in self.life_abilities(g)))
                self.portable(g)
    def test_zero_corpses_does_not_block_explicit_destroy(self):
        g=self.game((HUSK,'k74.destroy_own'),balance=0);self.play(g,HUSK);self.play(g,'k74.destroy_own')
        self.assertEqual((g.state.status,g.state.winner),('finished',2));self.assertFalse(self.markers(g))
        self.assertEqual(self.results(g)[0].actual_amount,0);self.assertFalse([e for e in g.events if e.kind=='hero_recovered']);self.portable(g)
    def test_positive_corpses_recover_from_explicit_destroy_and_clear_doom(self):
        g=self.game((HUSK,'k74.destroy_own'),balance=8);self.play(g,HUSK);self.play(g,'k74.destroy_own')
        self.assertEqual((self.hero(g).health,self.hero(g).doomed,g.state.status),(8,False,'playing'));self.portable(g)
    def test_nonlethal_damage_preserves_all_grants_and_balance(self):
        g=self.game((HUSK,'k74.small'),balance=7);self.play(g,HUSK);self.play(g,'k74.small')
        self.assertEqual((self.hero(g).health,self.bank(g)),(29,7));self.assertEqual(len(self.markers(g)),1)
        self.assertFalse(self.life_abilities(g)[0].consumed);self.assertFalse(self.results(g))
    def test_grant_survives_source_death_and_spends_its_genuine_corpse(self):
        g=self.game((HUSK,'k74.kill','k74.fatal'),balance=0);source=self.play(g,HUSK);self.play(g,'k74.kill',source)
        self.assertEqual(self.bank(g),1);self.play(g,'k74.fatal');self.assertEqual(self.hero(g).health,1)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertFalse(self.markers(g));self.portable(g)
    def test_source_silence_or_bounce_does_not_remove_already_granted_life(self):
        for cid in('k74.silence','k74.bounce'):
            g=self.game((HUSK,cid,'k74.fatal'),balance=7);source=self.play(g,HUSK);self.play(g,cid,source);self.play(g,'k74.fatal')
            self.assertEqual(self.hero(g).health,7);self.assertFalse(self.markers(g));self.portable(g)
    def test_source_control_transfer_does_not_transfer_original_hero_grant(self):
        g=self.game((HUSK,'k74.give','k74.fatal'),balance=7);source=self.play(g,HUSK);self.play(g,'k74.give',source);self.play(g,'k74.fatal')
        self.assertEqual((self.hero(g).health,self.bank(g),self.bank(g,2)),(7,0,11));self.assertFalse(self.life_abilities(g,2));self.portable(g)
    def test_current_copy_does_not_replay_battlecry_or_duplicate_life(self):
        g=self.game((HUSK,'k74.copy'));source=self.play(g,HUSK);self.play(g,'k74.copy',source)
        self.assertEqual(len(self.entities(g,HUSK)),2);self.assertEqual(len(self.life_abilities(g)),1);self.assertEqual(len(self.markers(g)),1)
    def test_once_consumed_life_cannot_save_a_second_fatal_hit(self):
        g=self.game((HUSK,'k74.fatal','k74.fatal'),balance=25);self.play(g,HUSK);self.play(g,'k74.fatal')
        self.assertEqual((self.hero(g).health,self.bank(g)),(20,5));self.play(g,'k74.fatal')
        self.assertEqual((g.state.status,g.state.winner,self.bank(g)),('finished',2,5));self.assertEqual(len(self.results(g)),1);self.portable(g)
    def test_new_real_battlecry_after_recovery_grants_a_new_independent_life(self):
        g=self.game((HUSK,'k74.fatal','k74.bounce','k74.fatal'),balance=25);source=self.play(g,HUSK);self.play(g,'k74.fatal')
        event=next(e for e in g.events if e.kind=='hero_died');death=next(d for d in g.state.death_history if d.zone==Zone.HERO)
        self.play(g,'k74.bounce',source);self.play(g,HUSK);self.assertEqual(len(self.markers(g)),1)
        # Ask only the pure old-acceptance query on a genuinely later ready state.
        # The same physical Husk's later marker is outside the original clock.
        c=RuleContext(g.state,death.entity_id,1,event=event,death=death)
        self.assertEqual(original_life_markers(c),())
        self.play(g,'k74.fatal');self.assertEqual((self.hero(g).health,self.bank(g)),(5,0));self.assertFalse(self.markers(g));self.portable(g)
    def test_two_actual_husk_battlecries_use_complete_existing_acceptance(self):
        g=self.game((HUSK,HUSK,'k74.fatal'),balance=25);self.play(g,HUSK);self.play(g,HUSK)
        self.assertEqual(len(self.markers(g)),2);self.play(g,'k74.fatal')
        self.assertEqual([x.actual_amount for x in self.results(g)],[20,5]);self.assertEqual(self.hero(g).health,20)
        self.assertFalse(self.markers(g));self.assertTrue(all(x.consumed for x in self.life_abilities(g)));self.portable(g)
    def test_opponent_only_destroy_never_consumes_friendly_hero_life(self):
        g=self.both_granted();self.play(g,'k74.destroy_enemy')
        self.assertEqual((self.bank(g),self.bank(g,2),self.hero(g,2).health),(7,0,11))
        self.assertEqual((len(self.markers(g)),len(self.markers(g,2))),(1,0));self.assertFalse(self.life_abilities(g)[0].consumed)
        self.assertEqual([x.player_id for x in self.results(g)],[2]);self.portable(g)
    def test_simultaneous_two_hero_deaths_keep_separate_owner_results(self):
        for left,right,status,winner in((7,11,'playing',None),(7,0,'finished',1),(0,0,'draw',None)):
            g=self.both_granted(left,right);self.play(g,'k74.both')
            self.assertEqual((g.state.status,g.state.winner),(status,winner));self.assertEqual(len(self.results(g)),2)
            self.assertEqual({r.player_id:r.actual_amount for r in self.results(g)},{1:left,2:right})
            self.assertFalse(self.markers(g));self.assertFalse(self.markers(g,2));self.portable(g)
    def test_same_damage_batch_credits_real_board_deaths_before_hero_rescue(self):
        g=self.game((HUSK,'k74.full_batch'),balance=0);self.play(g,HUSK);self.play(g,'k74.full_batch')
        self.assertEqual(self.hero(g).health,1);self.assertEqual([d.zone for d in g.state.death_history],[Zone.BOARD,Zone.HERO])
        self.assertEqual(self.results(g)[0].actual_amount,1);self.portable(g)
    def test_real_falric_provider_applies_before_same_batch_hero_debit(self):
        g=self.game((HUSK,'k74.kill','k74.fatal'),board=('CORE_EDR_003',),balance=0);source=self.play(g,HUSK)
        self.play(g,'k74.kill',source);self.play(g,'k74.fatal');self.assertEqual(self.hero(g).health,2);self.assertEqual(self.bank(g),0);self.portable(g)
    def test_hero_replacement_preserves_live_grant_and_public_player_effect(self):
        g=self.game((HUSK,'k74.replace','k74.fatal'));self.play(g,HUSK);old=self.hero(g).id;self.play(g,'k74.replace')
        self.assertNotEqual(self.hero(g).id,old);self.assertEqual(len(self.markers(g)),1);self.assertEqual(len(self.life_abilities(g)),1)
        new=self.hero(g).id;self.play(g,'k74.fatal');self.assertEqual((self.hero(g).id,self.hero(g).health),(new,7));self.portable(g)
    def test_hero_replacement_does_not_refresh_consumed_life(self):
        g=self.game((HUSK,'k74.fatal','k74.replace','k74.fatal'),balance=25);self.play(g,HUSK);self.play(g,'k74.fatal')
        self.play(g,'k74.replace');self.assertTrue(self.life_abilities(g)[0].consumed);self.play(g,'k74.fatal')
        self.assertEqual((g.state.status,self.bank(g)),('finished',5));self.assertEqual(len(self.results(g)),1);self.portable(g)
    def test_resource_wait_occurs_after_actual_recovery_and_marker_retirement(self):
        g=self.game((HUSK,'k74.fatal'),board=('k74.wait',));self.play(g,HUSK);self.play(g,'k74.fatal')
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.hero(g).health,7);self.assertFalse(self.markers(g))
        other=self.portable(g);self.choose(g,'keep');self.choose(other,'keep');self.assertEqual(g.snapshot(),other.snapshot());self.portable(g)
    def test_failed_choice_and_late_resource_reaction_restore_exact_transaction(self):
        g=self.game((HUSK,'k74.fatal'),board=('k74.wait',));self.play(g,HUSK);self.play(g,'k74.fatal');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.choose(g,'keep')
        g=self.game((HUSK,'k74.fatal'),board=('k74.breaker',));self.play(g,HUSK);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'k74.fatal')
        self.assertEqual(g.snapshot(),before);self.assertFalse(self.life_abilities(g)[0].consumed);self.assertEqual(len(self.markers(g)),1)
    def test_deathrattle_prohibition_uses_normal_terminal_without_rescue(self):
        g=self.game((HUSK,'k74.fatal'),board=('k74.block',));self.play(g,HUSK);self.play(g,'k74.fatal')
        self.assertEqual((g.state.status,self.bank(g)),('finished',7));self.assertFalse(self.results(g));self.portable(g)
    def test_concession_never_triggers_a_life_or_spends_corpses(self):
        g=self.game((HUSK,));self.play(g,HUSK);g.apply(Concede(1))
        self.assertEqual((g.state.status,g.state.winner,self.bank(g)),('finished',2,7));self.assertFalse(self.results(g));self.assertFalse(self.life_abilities(g)[0].consumed);self.portable(g)
    def test_recovery_is_not_an_ordinary_spell_heal(self):
        g=self.game((HUSK,'k74.fatal'));self.play(g,HUSK);self.play(g,'k74.fatal')
        self.assertEqual(len([e for e in g.events if e.kind=='hero_recovered']),1)
        self.assertFalse([e for e in g.events if e.kind in('healed','hero_healed')])
    def test_unknown_public_effect_source_and_future_fatal_receipt_rejected(self):
        g=self.game((HUSK,));self.play(g,HUSK);bad=g.snapshot();bad['state']['players']['1']['player_effects'][0]['source_id']=10**8
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())
        g=self.game((HUSK,'k74.fatal'),board=('k74.wait',));self.play(g,HUSK);self.play(g,'k74.fatal')
        bad=g.snapshot();bad['state']['hero_lethal_history'][0]['reference']['episode_id']=10**8
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())
    def test_player_effect_does_not_expose_original_hero_or_debit_material(self):
        g=self.game((HUSK,'k74.fatal'),board=('k74.wait',));self.play(g,HUSK)
        for p in(1,2):
            player=next(x for x in g.observe(p)['players']if x['id']==1);row=player['player_effects'][0]
            self.assertEqual(set(row),{'effect_key','card_id','effect_kind','remaining_turns'})
        self.play(g,'k74.fatal')
        for p in(1,2):
            visible=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for key in('hero_lethal_roots','hero_lethal_history','episode_id','root_id','zone_epoch','source_allocation','parked_hashes','balance_before','resource_operations'):
                self.assertNotIn('"'+key+'"',visible)
        self.choose(g,'keep')
    def test_forced_nonlethal_callback_does_not_invent_a_hero_episode(self):
        g=self.game();c=RuleContext(g.state,self.hero(g).id,1)
        with self.assertRaises(UnsupportedDefinitionError):self.r.behavior(LIFE)(c)


if __name__=='__main__':unittest.main()
