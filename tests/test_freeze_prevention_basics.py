"""Native continuous freeze prevention through original status/lifecycle paths."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, CardDefinition, CardType, DamageKind, EndTurn,
    Game, IllegalAction, Keyword, KeywordAuraSpec, PlayCard, PlayerSetup,
    Registry, ResolutionError, Scenario, SelectChoice, SnapshotError,
    SpellSchool, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.dormancy import MakeDormant, AwakenMinion
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Damage,
    Destroy, Freeze, InvokeBehavior, RequestChoice, ReturnToHand, Silence,
    Summon, Transform, Unfreeze)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

ROOT=Path(__file__).resolve().parents[1]
NATIVE='DRG_068'; BOLT='CS2_024'; FLAG=Keyword.CANT_BE_FROZEN
PIN='b05713403e0b71347b3701e6d852ac9a7302336c8b1ad8bca8cbeefc585958d7'
SILENCE_PIN='3d70c483b800230e5fee7ea9d4c3708e5970bcbf41aa4e4558dc1bf5525af324'


def evidence():
    value=json.loads((ROOT/'data/support/freeze-prevention-basics.json').read_bytes())
    if canonical_digest(value)!=PIN:raise ValueError('Complete native freeze protection evidence changed')
    return value


def registry():
    r=Registry('freeze-prevention-independent-v1');raw={x['id']:x for x in evidence()['records']}
    r.register_card(CardDefinition('fp.hero','Hero',CardType.HERO,health=30,metadata=metadata(collectible=False)))
    for cid,keywords in (('fp.body',()),('fp.immune',(Keyword.IMMUNE,)),('fp.hidden',())):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=2,health=15,keywords=keywords,metadata=metadata()))
    row=raw[NATIVE]
    r.register_card(CardDefinition(NATIVE,row['name'],CardType.MINION,cost=row['cost'],attack=row['attack'],health=row['health'],
        metadata=metadata_from_record(row),keyword_auras=(KeywordAuraSpec(FLAG,target='friendly_minions',include_self=True),)))
    row=raw[BOLT]
    r.register_behavior('fp.cb.bolt',lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL),Freeze(c.target_id,c.source_id)))
    r.register_card(CardDefinition(BOLT,row['name'],CardType.SPELL,cost=row['cost'],on_play='fp.cb.bolt',
        spell_school=SpellSchool.FROST,targeting=TargetSpec(),metadata=metadata_from_record(row)))
    operations={
        'freeze':lambda c:(Freeze(c.target_id,c.source_id),),
        'thaw':lambda c:(Unfreeze(c.target_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'kill':lambda c:(Destroy(c.target_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'transform':lambda c:(Transform(c.target_id,'fp.body'),),
        'control':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'base-copy':lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),),
        'dormant':lambda c:(MakeDormant(c.target_id,None,c.source_id),),
        'awaken':lambda c:(AwakenMinion(next(i for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id==NATIVE),c.source_id),),
        'summon':lambda c:(Summon(c.player_id,NATIVE),),
    }
    for key,body in operations.items():
        bid='fp.cb.'+key;r.register_behavior(bid,body)
        r.register_card(CardDefinition('fp.op.'+key,key,CardType.SPELL,on_play=bid,
            targeting=None if key in ('summon','awaken') else TargetSpec(),metadata=metadata()))
    def fail(c):raise ResolutionError('Deliberate freeze boundary rollback')
    r.register_behavior('fp.cb.fail',fail)
    def choice(c):
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',(
                Freeze(c.state.players[3-c.player_id].hero_id,c.source_id),
                InvokeBehavior('fp.cb.fail',c.source_id,c.player_id))),
        ),c.source_id),)
    r.register_behavior('fp.cb.wait-thaw',lambda c:choice(c) if dict(c.event.data).get('reason')=='cannot_be_frozen' else ())
    r.register_behavior('fp.cb.wait-block',lambda c:choice(c) if dict(c.event.data).get('reason')=='cannot_be_frozen' else ())
    for name,event in (('wait-thaw','unfrozen'),('wait-block','freeze_unchanged')):
        r.register_card(CardDefinition('fp.watch.'+name,name,CardType.MINION,health=15,metadata=metadata(),
            triggers=(TriggerSpec(event,'fp.cb.'+name),)))
    return r


class FreezePreventionTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy_board=(),*,enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('fp.hero',hand=hand,board=board,deck=('fp.body',)*10,max_mana=10,mana=10),
            PlayerSetup('fp.hero',hand=enemy_hand,board=enemy_board,deck=('fp.body',)*10,max_mana=10,mana=10)),seed=107),registry())
    def source(self,g,cid=NATIVE,player=1):
        return next(i for i in g.state.players[player].board if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        p=g.state.active_player;source=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        pos=len(g.state.players[p].board) if g.registry.card(cid).kind==CardType.MINION else None
        g.apply(PlayCard(p,source,target,pos));return source
    def freeze(self,g,target):return self.play(g,'fp.op.freeze',target)
    def choose(self,g,key='ok'):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(key,)))
    def check(self,g):
        saved=json.loads(json.dumps(g.snapshot()))
        variants=(Game.from_snapshot(saved,registry()),g.clone(),replay(build_replay(g),registry()))
        for other in variants:self.assertEqual(other.snapshot(),saved)
        return variants
    def blocked(self,g,target):
        self.assertFalse(g.state.entities[target].frozen);self.assertIsNone(g.state.entities[target].frozen_until_owner_turn)
        self.assertIn(FLAG,g.state.entities[target].keywords)

    def test_complete_native_raw_pin_source_metadata_and_small_executable_scope(self):
        packet=evidence();raw={x['id']:x for x in json.loads((ROOT/'data/extracted/cards.json').read_bytes())}
        self.assertEqual((len(packet['records']),packet['executable_representatives']),(21,[NATIVE,BOLT]))
        for row in packet['records']:self.assertEqual(row,raw[row['id']])
        r=registry();m,b=r.card(NATIVE),r.card(BOLT)
        self.assertEqual((m.cost,m.attack,m.health,m.metadata.tribes),(3,3,4,('elemental',)))
        self.assertEqual(m.keyword_auras,(KeywordAuraSpec(FLAG,target='friendly_minions',include_self=True),))
        self.assertEqual((b.cost,b.spell_school),(2,SpellSchool.FROST));self.assertIsNone(m.on_play);self.assertIsNone(m.battlecry)
        self.assertTrue(all(i not in r.cards for i in packet['evidence_only']))

    def test_silence_candidate_audit_preserves_all_carriers_without_inventing_immunity(self):
        packet=json.loads((ROOT/'data/support/silence-source-audit.json').read_bytes())
        self.assertEqual(canonical_digest(packet),SILENCE_PIN)
        self.assertEqual((len(packet['candidate_ids']),packet['counts'],packet['collectible_candidates']),
            (100,{'ENCHANTMENT':92,'WEAPON':4,'MINION':4},0))
        raw={x['id']:x for x in json.loads((ROOT/'data/extracted/cards.json').read_bytes())}
        for row in packet['records']:self.assertEqual(row,raw[row['id']])
        self.assertEqual(set(x['id'] for x in packet['records'] if x['type']=='MINION' and x['id'] in packet['candidate_ids']),
            {'TB_GP_03','TB_LEAGUE_REVIVAL_BrannBoss','CRED_15','CRED_50'})
        self.assertEqual(packet['executable_representatives'],[]);self.assertNotIn('cant_be_silenced',[k.value for k in Keyword])

    def test_native_in_hand_does_not_supply_freeze_protection(self):
        g=self.game((NATIVE,'fp.op.freeze'),('fp.body',));target=self.source(g,'fp.body');self.freeze(g,target)
        self.assertTrue(g.state.entities[target].frozen);self.assertNotIn(FLAG,g.state.entities[target].keywords)

    def test_native_protects_self_and_friendly_minions_but_not_heroes_or_enemies(self):
        g=self.game(('fp.op.freeze',)*4,(NATIVE,'fp.body'),('fp.body',));native=self.source(g);friend=self.source(g,'fp.body')
        hero=g.state.players[1].hero_id;enemy=self.source(g,'fp.body',2)
        for target in (native,friend,hero,enemy):self.freeze(g,target)
        self.blocked(g,native);self.blocked(g,friend);self.assertTrue(g.state.entities[hero].frozen);self.assertTrue(g.state.entities[enemy].frozen)
        self.assertEqual(sum(e.kind=='freeze_unchanged' for e in g.events),2);self.assertEqual(sum(e.kind=='frozen' for e in g.events),2);self.check(g)

    def test_native_frostbolt_still_deals_damage_and_its_freeze_is_prevented(self):
        g=self.game((BOLT,),(NATIVE,'fp.body'));target=self.source(g,'fp.body');source=self.play(g,BOLT,target)
        self.assertEqual(g.state.entities[target].health,12);self.blocked(g,target)
        events=[e for e in g.events if e.source_id==source]
        self.assertFalse(any(e.kind=='frozen' for e in events));self.assertTrue(any(e.kind=='freeze_unchanged' for e in events));self.check(g)

    def test_damage_immunity_does_not_itself_prevent_freeze(self):
        g=self.game((BOLT,),('fp.immune',));target=self.source(g,'fp.immune');self.play(g,BOLT,target)
        self.assertEqual(g.state.entities[target].health,15);self.assertTrue(g.state.entities[target].frozen)

    def test_playing_native_unfreezes_existing_minions_and_does_not_restore_old_deadline(self):
        g=self.game(('fp.op.freeze',NATIVE,'fp.op.kill','fp.op.freeze'),('fp.body',));target=self.source(g,'fp.body');self.freeze(g,target)
        self.assertTrue(g.state.entities[target].frozen);self.play(g,NATIVE);self.blocked(g,target)
        self.assertEqual(sum(e.kind=='unfrozen' and e.target_id==target for e in g.events),1)
        self.play(g,'fp.op.kill',self.source(g));self.assertFalse(g.state.entities[target].frozen)
        self.freeze(g,target);self.assertTrue(g.state.entities[target].frozen);self.check(g)

    def test_multiple_existing_frozen_minions_are_cleared_before_any_thaw_publication(self):
        g=self.game(('fp.op.freeze','fp.op.freeze',NATIVE),('fp.body','fp.body'));targets=tuple(g.state.players[1].board)
        for t in targets:self.freeze(g,t)
        self.play(g,NATIVE)
        for t in targets:self.blocked(g,t)
        self.assertEqual([e.target_id for e in g.events if e.kind=='unfrozen'],list(targets));self.check(g)

    def test_silencing_recipient_keeps_external_freeze_protection(self):
        g=self.game(('fp.op.silence','fp.op.freeze'),(NATIVE,'fp.body'));target=self.source(g,'fp.body');self.play(g,'fp.op.silence',target)
        self.assertTrue(g.state.entities[target].silenced);self.freeze(g,target);self.blocked(g,target)

    def test_silencing_native_source_removes_protection_and_allows_new_freeze(self):
        g=self.game(('fp.op.silence','fp.op.freeze'),(NATIVE,'fp.body'));native=self.source(g);target=self.source(g,'fp.body')
        self.play(g,'fp.op.silence',native);self.freeze(g,target)
        self.assertTrue(g.state.entities[target].frozen);self.assertNotIn(FLAG,g.state.entities[target].keywords);self.check(g)

    def test_native_source_leaving_board_or_transforming_removes_its_contribution(self):
        for operation in ('kill','bounce','transform'):
            with self.subTest(operation=operation):
                g=self.game(('fp.op.'+operation,'fp.op.freeze'),(NATIVE,'fp.body'));native=self.source(g);target=self.source(g,'fp.body')
                self.play(g,'fp.op.'+operation,native);self.freeze(g,target);self.assertTrue(g.state.entities[target].frozen);self.check(g)

    def test_native_control_transfer_moves_protection_and_thaws_new_controller_minions(self):
        g=self.game(('fp.op.freeze','fp.op.control','fp.op.freeze'),(NATIVE,'fp.body'),('fp.body',))
        old=self.source(g,'fp.body');new=self.source(g,'fp.body',2);self.freeze(g,new);self.assertTrue(g.state.entities[new].frozen)
        self.play(g,'fp.op.control',self.source(g));self.blocked(g,new);self.freeze(g,old);self.assertTrue(g.state.entities[old].frozen);self.check(g)

    def test_native_current_copy_keeps_aura_while_current_silenced_copy_does_not(self):
        for silenced in (False,True):
            with self.subTest(silenced=silenced):
                g=self.game(('fp.op.copy','fp.op.kill','fp.op.silence','fp.op.freeze'),(NATIVE,'fp.body'));native=self.source(g);target=self.source(g,'fp.body')
                if silenced:self.play(g,'fp.op.silence',native)
                self.play(g,'fp.op.copy',native);self.play(g,'fp.op.kill',native);self.freeze(g,target)
                self.assertEqual(g.state.entities[target].frozen,silenced);self.check(g)

    def test_base_copy_of_silenced_native_restores_only_printed_aura(self):
        g=self.game(('fp.op.silence','fp.op.base-copy','fp.op.freeze'),(NATIVE,'fp.body'));native=self.source(g);target=self.source(g,'fp.body')
        self.play(g,'fp.op.silence',native);self.play(g,'fp.op.base-copy',native);self.freeze(g,target);self.blocked(g,target)

    def test_copy_of_unprotected_frozen_enemy_into_protected_side_is_not_refrozen(self):
        g=self.game(('fp.op.freeze','fp.op.copy'),(NATIVE,),('fp.body',));enemy=self.source(g,'fp.body',2);self.freeze(g,enemy)
        self.play(g,'fp.op.copy',enemy);copy=self.source(g,'fp.body');self.blocked(g,copy)
        self.assertTrue(g.state.entities[enemy].frozen);self.check(g)

    def test_summoning_native_activates_continuous_protection_without_on_play(self):
        g=self.game(('fp.op.freeze','fp.op.summon'),('fp.body',));target=self.source(g,'fp.body');self.freeze(g,target)
        self.play(g,'fp.op.summon');self.blocked(g,target)
        self.assertFalse(any(p.card_id==NATIVE for p in g.state.play_history));self.assertFalse(g.state.battlecry_history);self.check(g)

    def test_dormant_source_loses_aura_and_awakening_thaws_existing_friendly_freeze(self):
        g=self.game(('fp.op.dormant','fp.op.freeze','fp.op.awaken'),(NATIVE,'fp.body'));native=self.source(g);target=self.source(g,'fp.body')
        self.play(g,'fp.op.dormant',native);self.freeze(g,target);self.assertTrue(g.state.entities[target].frozen)
        self.play(g,'fp.op.awaken');self.blocked(g,target);self.check(g)

    def test_multiple_sources_do_not_stack_thaw_or_remove_surviving_protection(self):
        g=self.game(('fp.op.kill','fp.op.freeze'),(NATIVE,NATIVE,'fp.body'));target=self.source(g,'fp.body');self.play(g,'fp.op.kill',self.source(g))
        self.freeze(g,target);self.blocked(g,target);self.assertFalse(any(e.kind=='unfrozen' for e in g.events))

    def test_native_thaw_wait_restores_clones_and_replays_one_paid_entry(self):
        g=self.game(('fp.op.freeze',NATIVE),('fp.body','fp.watch.wait-thaw'));target=self.source(g,'fp.body');self.freeze(g,target)
        source=self.play(g,NATIVE);self.assertIsNotNone(g.state.pending_choice);self.blocked(g,target)
        saved=g.snapshot();variants=self.check(g)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for other in (g,*variants):
            self.choose(other);self.blocked(other,target);self.assertEqual(other.state.players[1].mana,7)
            self.assertEqual(sum(p.source_id==source for p in other.state.play_history),1)
        self.check(g)

    def test_prevented_native_frostbolt_wait_keeps_damage_and_recovery_atomic(self):
        g=self.game((BOLT,),(NATIVE,'fp.body','fp.watch.wait-block'));target=self.source(g,'fp.body');source=self.play(g,BOLT,target)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.entities[target].health,12);self.blocked(g,target)
        saved=g.snapshot();variants=self.check(g)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for other in (g,*variants):
            self.choose(other);self.assertEqual((other.state.entities[target].health,other.state.players[1].mana),(12,8));self.blocked(other,target)
            self.assertEqual(sum(p.source_id==source for p in other.state.play_history),1)
        self.check(g)

    def test_thawed_minion_can_use_its_original_remaining_attack_opportunity(self):
        g=self.game(('fp.op.freeze',NATIVE),('fp.body',));target=self.source(g,'fp.body');self.freeze(g,target)
        with self.assertRaises(IllegalAction):g.apply(Attack(1,target,g.state.players[2].hero_id))
        self.play(g,NATIVE);g.apply(Attack(1,target,g.state.players[2].hero_id))
        self.assertEqual((g.state.entities[target].attacks_this_turn,g.state.entities[g.state.players[2].hero_id].health),(1,28))

    def test_thaw_does_not_refund_spent_attack_or_native_summoning_sickness(self):
        g=self.game(('fp.op.freeze',NATIVE),('fp.body',));target=self.source(g,'fp.body');g.apply(Attack(1,target,g.state.players[2].hero_id))
        self.freeze(g,target);source=self.play(g,NATIVE);self.blocked(g,target)
        for attacker in (target,source):
            with self.assertRaises(IllegalAction):g.apply(Attack(1,attacker,g.state.players[2].hero_id))

    def test_explicit_thaw_and_natural_end_do_not_repeat_already_cleared_status(self):
        g=self.game(('fp.op.freeze',NATIVE,'fp.op.thaw'),('fp.body',));target=self.source(g,'fp.body');self.freeze(g,target);self.play(g,NATIVE)
        self.play(g,'fp.op.thaw',target);g.apply(EndTurn(1))
        self.assertEqual(sum(e.kind=='unfrozen' and e.target_id==target for e in g.events),1);self.check(g)

    def test_frostbolt_killing_native_source_does_not_leave_protection_for_later_effects(self):
        g=self.game((BOLT,BOLT,'fp.op.freeze'),(NATIVE,'fp.body'));native=self.source(g);target=self.source(g,'fp.body')
        self.play(g,BOLT,native);self.blocked(g,native);self.play(g,BOLT,native)
        self.assertEqual(g.state.entities[native].zone,Zone.GRAVEYARD);self.freeze(g,target);self.assertTrue(g.state.entities[target].frozen);self.check(g)

    def test_rehashed_snapshot_rejects_frozen_deadline_under_live_protection(self):
        g=self.game(board=(NATIVE,'fp.body'));target=self.source(g,'fp.body');bad=deepcopy(g.snapshot())
        bad['state']['entities'][str(target)]['frozen_until_owner_turn']=1
        bad['state_hash']=canonical_hash({k:v for k,v in bad.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as raised:Game.from_snapshot(bad,registry())
        self.assertNotIn('digest mismatch',str(raised.exception));self.check(g)

    def test_read_only_snapshot_does_not_emit_thaw_events_or_change_state(self):
        g=self.game(('fp.op.freeze',NATIVE),('fp.body',));target=self.source(g,'fp.body');self.freeze(g,target);self.play(g,NATIVE)
        saved=g.snapshot();events=g.events
        for _ in range(3):self.assertEqual(g.snapshot(),saved);self.assertEqual(g.events,events)

    def test_public_view_exposes_protected_status_without_hidden_cards_or_engine_facts(self):
        g=self.game(board=(NATIVE,'fp.body'),enemy_hand=('fp.hidden',));self.assertNotIn('fp.hidden',json.dumps(g.for_player(1).observe()))
        for player in (1,2):
            wire=json.dumps((g.for_player(player).observe(),g.for_player(player).legal_actions()))
            for field in ('owner_turn_history','frozen_until_owner_turn','source_sha256','keyword_auras'):self.assertNotIn(field,wire)
        self.check(g)

    def test_aura_declaration_keeps_native_scope_and_prior_schema_is_rejected(self):
        for fields in (dict(target='friendly_hero'),dict(target='friendly_hand_minions'),dict(target='friendly_minions',adjacent_only=True)):
            with self.subTest(fields=fields):
                with self.assertRaises(ValueError):KeywordAuraSpec(FLAG,**fields)
        g=self.game(board=(NATIVE,));saved=g.snapshot();self.assertEqual((g.ruleset.id,g.mechanics.version,saved['schema_version']),('prototype-v302',CORE_EFFECTS_VERSION,266))
        saved['schema_version']=223
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())


if __name__=='__main__':unittest.main()
