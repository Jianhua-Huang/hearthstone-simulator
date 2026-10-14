"""Independent native Deathrattle prohibition, original acceptance and lifecycle."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition,CardType,Game,IllegalAction,Keyword,KeywordAuraSpec,
    PlayCard,PlayerSetup,Registry,ResolutionError,Resource,Scenario,SelectChoice,SnapshotError,
    TargetSpec,TriggerSpec,Zone,RecoverHero)
from hs_sim.engine.deathrattles import deathrattles_can_trigger,triggerable_deathrattles,validate_prohibition_carrier
from hs_sim.engine.dormancy import MakeDormant,AwakenMinion
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,CopyMinion,Damage,DamageBatch,
    Destroy,Draw,EquipWeapon,GainArmor,GrantKeyword,InvokeBehavior,RequestChoice,ReturnToHand,
    Silence,Summon,Transform,TriggerDeathrattles)
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_sources import DeathQuery,death_candidates
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

ROOT=Path(__file__).resolve().parents[1]
NATIVE='YOP_012';ACTIVE='ICC_052';RATTLE='EX1_012';FLAG=Keyword.DEATHRATTLE_SUPPRESSOR
PIN='c6874ff843c110cbc435577945a7dad84537e64dadf6b4ff1e219a15d49673da'

def evidence():
    packet=json.loads((ROOT/'data/support/deathrattle-prohibition-basics.json').read_bytes())
    if canonical_digest(packet)!=PIN:raise ValueError('Complete native Deathrattle prohibition evidence changed')
    return packet

def registry():
    r=Registry('independent-deathrattle-prohibition-v1');raw={c['id']:c for c in evidence()['records']}
    r.register_card(CardDefinition('ds.hero','Hero',CardType.HERO,health=30,metadata=metadata(collectible=False)))
    r.register_card(CardDefinition('ds.body','Body',CardType.MINION,attack=2,health=20,metadata=metadata()))
    row=raw[NATIVE]
    r.register_card(CardDefinition(NATIVE,row['name'],CardType.MINION,cost=row['cost'],attack=row['attack'],health=row['health'],
        keywords=(FLAG,),metadata=metadata_from_record(row)))
    r.register_behavior('ds.cb.draw',lambda c:(Draw(c.player_id,1),))
    row=raw[RATTLE]
    r.register_card(CardDefinition(RATTLE,row['name'],CardType.MINION,cost=row['cost'],attack=row['attack'],health=row['health'],
        spell_damage=1,deathrattle='ds.cb.draw',metadata=metadata_from_record(row)))
    r.register_behavior('ds.cb.native-active',lambda c:(TriggerDeathrattles(c.target_id,c.source_id),))
    row=raw[ACTIVE]
    r.register_card(CardDefinition(ACTIVE,row['name'],CardType.SPELL,cost=row['cost'],on_play='ds.cb.native-active',
        target_rule='triggerable_deathrattle',targeting=TargetSpec(relation='friendly',kinds=(CardType.MINION,),zones=(Zone.BOARD,)),
        metadata=metadata_from_record(row)))
    r.register_behavior('ds.cb.armor',lambda c:(GainArmor(c.player_id,1),))
    r.register_card(CardDefinition('ds.weapon','Death weapon fixture',CardType.WEAPON,attack=1,durability=2,
        deathrattle='ds.cb.armor',metadata=metadata()))
    r.register_card(CardDefinition('ds.plainweapon','Replacement fixture',CardType.WEAPON,attack=1,durability=2,metadata=metadata()))
    def fail(c):raise ResolutionError('Deliberate prohibition boundary rollback')
    r.register_behavior('ds.cb.fail',fail)
    def choice(c):
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('block','Install source',(Summon(c.player_id,NATIVE),GainArmor(c.player_id,1))),
            ChoiceOption('bad','Fail',(GainArmor(c.player_id,4),InvokeBehavior('ds.cb.fail',c.source_id,c.player_id))),
        ),c.source_id),)
    r.register_behavior('ds.cb.wait',choice)
    r.register_behavior('ds.cb.watch',lambda c:choice(c) if c.state.death_history[-1].deathrattles_blocked else ())
    r.register_card(CardDefinition('ds.wait','Waiting body fixture',CardType.MINION,health=2,deathrattle='ds.cb.wait',metadata=metadata()))
    r.register_card(CardDefinition('ds.watch','Death observer fixture',CardType.MINION,health=20,
        triggers=(TriggerSpec('minion_died','ds.cb.watch'),),metadata=metadata()))
    r.register_behavior('ds.cb.recover',lambda c:(RecoverHero(c.hero_lethal,5),))
    def nested(c):
        return (RequestChoice(c.player_id,(ChoiceOption('nested','Continue',(
            RecoverHero(c.hero_lethal,5),Summon(c.player_id,NATIVE),Damage(c.state.players[3-c.player_id].hero_id,99,c.source_id))),),c.source_id),)
    r.register_behavior('ds.cb.nested',nested)
    for name,behavior in (('save','ds.cb.recover'),('wait','ds.cb.nested')):
        r.register_card(CardDefinition('ds.hero.'+name,name,CardType.HERO,health=30,deathrattle=behavior,metadata=metadata(collectible=False)))
    operations={
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'transform':lambda c:(Transform(c.target_id,'ds.body'),),
        'control':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'base-copy':lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),),
        'dormant':lambda c:(MakeDormant(c.target_id,None,c.source_id),),
        'awaken':lambda c:(AwakenMinion(next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==NATIVE),c.source_id),),
        'active':lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),
        'all':lambda c:(DamageBatch(tuple(Damage(i,20,c.source_id) for p in c.state.players.values() for i in p.board)),),
        'equip':lambda c:(EquipWeapon(c.player_id,'ds.plainweapon'),),
        'summon':lambda c:(Summon(c.player_id,NATIVE),),
        'fatal':lambda c:(Damage(c.state.players[c.player_id].hero_id,99,c.source_id),),
    }
    domain=TargetSpec(kinds=(CardType.MINION,CardType.WEAPON,CardType.HERO),zones=(Zone.BOARD,Zone.WEAPON,Zone.HERO))
    for name,body in operations.items():
        r.register_behavior('ds.cb.'+name,body)
        r.register_card(CardDefinition('ds.op.'+name,name,CardType.SPELL,on_play='ds.cb.'+name,
            targeting=None if name in ('awaken','all','equip','summon','fatal') else domain,metadata=metadata()))
    return r

class DeathrattleProhibitionTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),*,weapon=None,hero='ds.hero',enemy_hero='ds.hero',enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero,hand=hand,board=board,deck=('ds.body',)*8,max_mana=10,mana=10,weapon_card_id=weapon),
            PlayerSetup(enemy_hero,hand=enemy_hand,board=enemy,deck=('ds.body',)*8,max_mana=10,mana=10)),seed=108),registry())
    def find(self,g,cid,player=1):return next(i for i in g.state.players[player].board if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        p=g.state.active_player;i=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        pos=len(g.state.players[p].board) if g.registry.card(cid).kind==CardType.MINION else None
        g.apply(PlayCard(p,i,target,pos));return i
    def choose(self,g,key='ok'):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(key,)))
    def check(self,g):
        saved=json.loads(json.dumps(g.snapshot()))
        others=(Game.from_snapshot(saved,registry()),g.clone(),replay(build_replay(g),registry()))
        for other in others:self.assertEqual(other.snapshot(),saved)
        return others
    def current_draws(self,g):return len(g.state.draw_history)
    def armor(self,g,p=1):return g.state.entities[g.state.players[p].hero_id].armor
    def rehash(self,s):s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})

    def test_native_full_raw_pin_metadata_and_only_necessary_bodies(self):
        p=evidence();raw={c['id']:c for c in json.loads((ROOT/'data/extracted/cards.json').read_bytes())}
        self.assertEqual((p['candidate_ids'],p['executable_representatives']),([NATIVE,'YOP_012e'],[NATIVE,ACTIVE,RATTLE]))
        for row in p['records']:self.assertEqual(row,raw[row['id']])
        r=registry();n,a,d=r.card(NATIVE),r.card(ACTIVE),r.card(RATTLE)
        self.assertEqual((n.cost,n.attack,n.health,n.metadata.tribes,n.keywords),(3,2,5,('undead',),(FLAG,)))
        self.assertEqual((n.on_play,n.battlecry,n.deathrattle),(None,None,None))
        self.assertEqual((a.cost,d.cost,d.attack,d.health,d.spell_damage),(1,2,1,1,1));self.assertNotIn('YOP_012e',r.cards)

    def test_native_in_hand_does_not_prohibit(self):
        g=self.game((NATIVE,ACTIVE),(RATTLE,));self.play(g,ACTIVE,self.find(g,RATTLE))
        self.assertTrue(deathrattles_can_trigger(g.state));self.assertEqual(self.current_draws(g),1);self.check(g)

    def test_source_on_either_side_prohibits_both_sides_without_erasing_abilities(self):
        for board,enemy in (((NATIVE,RATTLE),()),((RATTLE,),(NATIVE,))):
            with self.subTest(board=board):
                g=self.game(('ds.op.active',),board,enemy);target=self.find(g,RATTLE)
                self.assertFalse(deathrattles_can_trigger(g.state));self.assertEqual(len(active_abilities(g.state.entities[target],'deathrattle')),1)
                self.assertFalse(triggerable_deathrattles(g.state,g.state.entities[target]));self.play(g,'ds.op.active',target)
                self.assertEqual((self.current_draws(g),len(g.state.deathrattle_history),len(g.state.death_history)),(0,0,0));self.check(g)

    def test_native_target_rule_rejects_and_transaction_keeps_payment_hand_rng_history(self):
        g=self.game((ACTIVE,),(NATIVE,RATTLE,'ds.body'));target=self.find(g,RATTLE)
        source=g.state.players[1].hand[0];action=PlayCard(1,source,target);saved=g.snapshot()
        self.assertNotIn(action,g.legal_actions())
        public=g.for_player(1).legal_actions();self.assertIsNone(public['error'])
        self.assertFalse(any(a['type']=='play_card' for a in public['actions']))
        with self.assertRaises(IllegalAction):g.apply(action)
        self.assertEqual(g.snapshot(),saved);self.check(g)

    def test_native_active_draws_once_and_pays_once_when_unblocked(self):
        g=self.game((ACTIVE,),(RATTLE,'ds.body'));target=self.find(g,RATTLE);source=g.state.players[1].hand[0]
        self.assertIn(PlayCard(1,source,target),g.legal_actions());self.assertNotIn(PlayCard(1,source,self.find(g,'ds.body')),g.legal_actions())
        public=g.for_player(1).legal_actions();self.assertIsNone(public['error'])
        commands=[a for a in public['actions'] if a['type']=='play_card'];self.assertEqual(len(commands),1)
        result=g.for_player(1).submit({'revision':public['revision'],'action':commands[0]})
        self.assertTrue(result['accepted'],result['error']);self.assertEqual((self.current_draws(g),g.state.players[1].mana),(1,9))
        self.assertFalse(g.state.death_history);self.assertEqual(g.state.deathrattle_history[0].capture.origin,'effect');self.check(g)

    def test_blocked_natural_death_retains_death_material_corpses_and_historical_identity(self):
        g=self.game(('ds.op.kill',),(NATIVE,RATTLE));target=self.find(g,RATTLE);self.play(g,'ds.op.kill',target)
        death=g.state.death_history[0];self.assertTrue(death.deathrattles_blocked)
        self.assertTrue(any(a.kind=='deathrattle' for a in death.abilities));self.assertEqual((self.current_draws(g),g.state.next_deathrattle_id),(0,1))
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES],1)
        self.assertEqual([d.card_id for d in death_candidates(g.state,g.registry,1,DeathQuery(has_deathrattle=True))],[RATTLE]);self.check(g)

    def test_source_silence_restores_target_and_active_behavior(self):
        g=self.game(('ds.op.silence',ACTIVE),(NATIVE,RATTLE));self.play(g,'ds.op.silence',self.find(g,NATIVE))
        self.assertTrue(deathrattles_can_trigger(g.state));self.play(g,ACTIVE,self.find(g,RATTLE));self.assertEqual(self.current_draws(g),1);self.check(g)

    def test_recipient_silence_does_not_remove_external_prohibition(self):
        g=self.game(('ds.op.silence',),(NATIVE,RATTLE));self.play(g,'ds.op.silence',self.find(g,RATTLE))
        self.assertFalse(deathrattles_can_trigger(g.state));self.assertIn(FLAG,g.state.entities[self.find(g,NATIVE)].keywords);self.check(g)

    def test_source_destruction_allows_a_new_natural_acceptance(self):
        g=self.game(('ds.op.kill','ds.op.kill'),(NATIVE,RATTLE));self.play(g,'ds.op.kill',self.find(g,NATIVE));self.play(g,'ds.op.kill',self.find(g,RATTLE))
        self.assertEqual(self.current_draws(g),1);self.assertFalse(g.state.death_history[-1].deathrattles_blocked);self.check(g)

    def test_source_bounce_and_transform_remove_prohibition(self):
        for op in ('bounce','transform'):
            with self.subTest(op=op):
                g=self.game(('ds.op.'+op,ACTIVE),(NATIVE,RATTLE));self.play(g,'ds.op.'+op,self.find(g,NATIVE));self.play(g,ACTIVE,self.find(g,RATTLE))
                self.assertEqual(self.current_draws(g),1);self.check(g)

    def test_control_transfer_keeps_global_scope(self):
        g=self.game(('ds.op.control','ds.op.active'),(NATIVE,RATTLE));self.play(g,'ds.op.control',self.find(g,NATIVE));self.play(g,'ds.op.active',self.find(g,RATTLE))
        self.assertFalse(deathrattles_can_trigger(g.state));self.assertEqual(self.current_draws(g),0);self.check(g)

    def test_source_current_copy_keeps_native_lifecycle(self):
        g=self.game(('ds.op.copy','ds.op.kill','ds.op.active'),(NATIVE,RATTLE));original=self.find(g,NATIVE);self.play(g,'ds.op.copy',original);self.play(g,'ds.op.kill',original)
        self.assertFalse(deathrattles_can_trigger(g.state));self.play(g,'ds.op.active',self.find(g,RATTLE));self.assertEqual(self.current_draws(g),0);self.check(g)

    def test_silenced_current_copy_stays_silenced_and_base_copy_restores_printed_source(self):
        g=self.game(('ds.op.silence','ds.op.copy','ds.op.base-copy'),(NATIVE,));original=self.find(g,NATIVE);self.play(g,'ds.op.silence',original);self.play(g,'ds.op.copy',original)
        self.assertTrue(deathrattles_can_trigger(g.state));self.play(g,'ds.op.base-copy',original);self.assertFalse(deathrattles_can_trigger(g.state));self.check(g)

    def test_source_dormancy_removes_and_awakening_restores_prohibition(self):
        g=self.game(('ds.op.dormant',ACTIVE,'ds.op.awaken','ds.op.active'),(NATIVE,RATTLE));self.play(g,'ds.op.dormant',self.find(g,NATIVE))
        self.play(g,ACTIVE,self.find(g,RATTLE));self.play(g,'ds.op.awaken');self.play(g,'ds.op.active',self.find(g,RATTLE))
        self.assertEqual(self.current_draws(g),1);self.assertFalse(deathrattles_can_trigger(g.state));self.check(g)

    def test_multiple_sources_require_all_live_sources_to_leave(self):
        g=self.game(('ds.op.kill','ds.op.active','ds.op.kill',ACTIVE),(NATIVE,RATTLE),(NATIVE,));self.play(g,'ds.op.kill',self.find(g,NATIVE))
        self.play(g,'ds.op.active',self.find(g,RATTLE));self.assertEqual(self.current_draws(g),0)
        self.play(g,'ds.op.kill',self.find(g,NATIVE,2));self.play(g,ACTIVE,self.find(g,RATTLE));self.assertEqual(self.current_draws(g),1);self.check(g)

    def test_simultaneous_source_removal_uses_original_post_removal_acceptance_window(self):
        g=self.game(('ds.op.all',),(NATIVE,RATTLE));self.play(g,'ds.op.all');self.assertEqual(self.current_draws(g),1)
        self.assertEqual(len({d.batch for d in g.state.death_history}),1);self.assertFalse(any(d.deathrattles_blocked for d in g.state.death_history));self.check(g)

    def test_weapon_destruction_and_replacement_share_prohibition(self):
        for op in ('kill','equip'):
            with self.subTest(op=op):
                g=self.game(('ds.op.'+op,),(NATIVE,),weapon='ds.weapon');self.play(g,'ds.op.'+op,g.state.players[1].weapon_id if op=='kill' else None)
                self.assertEqual((self.armor(g),len(g.state.deathrattle_history)),(0,0));self.assertTrue(g.state.death_history[0].deathrattles_blocked);self.check(g)

    def test_blocked_death_receipt_precedes_ordinary_reaction_capture_and_choice(self):
        g=self.game(('ds.op.kill',),(NATIVE,RATTLE,'ds.watch'));self.play(g,'ds.op.kill',self.find(g,RATTLE))
        self.assertIsNotNone(g.state.pending_choice);self.assertTrue(g.state.death_history[0].deathrattles_blocked)
        variants=self.check(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g)
        for other in variants:self.choose(other);self.assertEqual(other.snapshot(),g.snapshot())
        self.assertEqual((self.armor(g),self.current_draws(g)),(1,0));self.check(g)

    def test_already_accepted_active_body_finishes_after_source_enters(self):
        g=self.game((ACTIVE,'ds.op.active'),('ds.wait',));target=self.find(g,'ds.wait');self.play(g,ACTIVE,target)
        variants=self.check(g);self.choose(g,'block')
        for other in variants:self.choose(other,'block');self.assertEqual(other.snapshot(),g.snapshot())
        self.assertTrue(g.state.deathrattle_history[0].completed);self.assertEqual(self.armor(g),1)
        self.play(g,'ds.op.active',target);self.assertEqual(len(g.state.deathrattle_history),1);self.check(g)

    def test_already_accepted_natural_body_finishes_after_source_enters(self):
        g=self.game(('ds.op.kill',),('ds.wait',));self.play(g,'ds.op.kill',self.find(g,'ds.wait'));self.check(g);self.choose(g,'block')
        self.assertTrue(g.state.deathrattle_history[0].completed);self.assertFalse(g.state.death_history[0].deathrattles_blocked);self.check(g)

    def test_hero_natural_death_prohibition_uses_ordinary_terminal(self):
        g=self.game(('ds.op.fatal',),(NATIVE,),hero='ds.hero.save');self.play(g,'ds.op.fatal')
        self.assertEqual((g.state.status,g.state.winner),('finished',2));self.assertFalse(g.state.deathrattle_history);self.assertFalse(g.state.hero_lethal_history);self.check(g)

    def test_unblocked_hero_natural_body_keeps_existing_recovery(self):
        g=self.game(('ds.op.fatal',),hero='ds.hero.save');self.play(g,'ds.op.fatal')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,5);self.assertEqual(g.state.status,'playing');self.check(g)

    def test_new_nested_hero_death_is_blocked_without_losing_prior_root_proof(self):
        g=self.game(('ds.op.fatal',),hero='ds.hero.wait',enemy_hero='ds.hero.save');self.play(g,'ds.op.fatal');self.check(g);self.choose(g,'nested')
        self.assertEqual((g.state.status,g.state.winner),('finished',1));self.assertTrue(g.state.death_history[-1].deathrattles_blocked)
        self.assertEqual(len(g.state.deathrattle_history),1);self.check(g)

    def test_rehashed_blocked_receipt_cannot_claim_an_accepted_natural_body(self):
        g=self.game(('ds.op.kill',),(RATTLE,));self.play(g,'ds.op.kill',self.find(g,RATTLE));bad=deepcopy(g.snapshot())
        bad['state']['death_history'][0]['deathrattles_blocked']=True;self.rehash(bad)
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())
        self.check(g)

    def test_native_source_is_not_a_new_grant_aura_or_other_card_type(self):
        with self.assertRaises(ValueError):GrantKeyword(1,FLAG)
        with self.assertRaises(ValueError):KeywordAuraSpec(FLAG,target='friendly_minions')
        r=Registry('invalid-native-source')
        with self.assertRaises(ValueError):r.register_card(CardDefinition('wrong','Wrong',CardType.SPELL,keywords=(FLAG,),metadata=metadata()))
        g=self.game(board=(NATIVE,));s=g.snapshot();self.assertEqual((g.ruleset.id,g.mechanics.version,s['schema_version']),('prototype-v302',CORE_EFFECTS_VERSION,266))
        with self.assertRaises(ValueError):validate_prohibition_carrier(g.registry,'ds.body',CardType.MINION,g.state.entities[self.find(g,NATIVE)].abilities)
        s['schema_version']=224
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())

    def test_player_information_keeps_receipts_and_hidden_cards_private(self):
        g=self.game((ACTIVE,),(NATIVE,RATTLE),enemy_hand=('ds.body',))
        for p in (1,2):
            self.assertIsNone(g.for_player(p).legal_actions()['error'])
            wire=json.dumps((g.for_player(p).observe(),g.for_player(p).legal_actions()))
            for key in ('deathrattles_blocked','deathrattle_history','source_sha256','prototype-v290'):self.assertNotIn(key,wire)
        self.assertNotIn('ds.body',json.dumps(g.for_player(1).observe()));self.check(g)

if __name__=='__main__':unittest.main()
