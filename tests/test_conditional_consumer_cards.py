"""Actual conditional consumers and the original freeze-group continuation."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT, historical_definition_digests
from copy import deepcopy
from dataclasses import asdict,replace
import json,unittest
from pathlib import Path
from hs_sim.cards import build_registry
from hs_sim.cards.conditional_consumer_cards import (CULTIST,TYRANT,KEEPER,BITTER,AXE,CLAWS,AUCTIONEER,WAYGATE,ROOTS,BATCH_HASH,load_batch)
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,DeckPolicy,DeckSpec,EndTurn,Game,
    IllegalAction,Keyword,MatchSetup,OpeningHook,PlayCard,PlayerSetup,Rarity,Scenario,SelectChoice,SnapshotError,SpellSchool,TargetSpec,TriggerSpec,UseHandAction,Zone)
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChangeManaCrystals,ChoiceOption,CopyMinion,Damage,Destroy,Draw,
    Heal,InvokeBehavior,ModifyWeapon,RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CostSpec
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry as representative
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.spell_target_sequences import FreezeAdjacentThenDestroyDamaged,FreezeOriginalGroupMember,DestroyDamagedFrozenGroup
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.engine.zones import CardReference,CopyCard,ModifyStoredCost
from hs_sim.targets import canonical_digest

ROOT=Path(__file__).resolve().parents[1];YETI='CORE_CS2_182';FIREBALL='CORE_CS2_029';BOLT='CORE_CS2_024';DORMANT='EDR_979';REPLACEMENT='EDR_253'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


def registry():
    r=build_registry();r.register_behavior('k81.noop',lambda c:())
    def fail(c):raise ResolutionError('K81 deliberate failure')
    r.register_behavior('k81.fail',fail)
    for name,attack,health,tribes in(('left',1,5,()),('middle',1,5,()),('right',1,5,()),('fodder',1,1,()),('dragon',1,5,('dragon',)),('all',1,5,('all',))):
        r.register_card(CardDefinition('k81.'+name,name,CardType.MINION,attack=attack,health=health,metadata=replace(META,tribes=tribes)))
    r.register_card(CardDefinition('k81.location','location',CardType.LOCATION,durability=2,on_use='k81.noop',metadata=META))
    def first(c,cid,p=2,zone='board'):
        return next(c.state.entities[i]for i in getattr(c.state.players[p],zone)if c.state.entities[i].card_id==cid)
    def wait(c):
        items=(('keep','Keep','noop'),('heal','Heal primary','heal_middle'),('hurt','Hurt right','hurt_right'),('bounce','Bounce and reenter right','reenter_right'),
            ('replace','Replace middle','replace_middle'),('control','Take right','take_right'),('fail','Fail','fail'))
        return(RequestChoice(c.player_id,tuple(ChoiceOption(key,label,(InvokeBehavior('k81.'+body,c.source_id,c.player_id),))for key,label,body in items),source_id=c.source_id,prompt='Original group'),)
    r.register_behavior('k81.heal_middle',lambda c:(Heal(first(c,'k81.middle').id,5,c.source_id),))
    r.register_behavior('k81.hurt_right',lambda c:(Damage(first(c,'k81.right').id,1,c.source_id),))
    def reenter(c):
        entity=first(c,'k81.right')
        return(ReturnToHand(entity.id),SummonFromZone(2,zone=Zone.HAND,selection='first',source_id=c.source_id,cause=SummonCause.capture(c)))
    def replace_middle(c):
        return(ReturnToHand(first(c,'k81.middle').id),SummonByCard(2,(SummonEntryMaterial(YETI),),SummonCause.capture(c)))
    r.register_behavior('k81.reenter_right',reenter);r.register_behavior('k81.replace_middle',replace_middle)
    r.register_behavior('k81.take_right',lambda c:(ChangeControl(first(c,'k81.right').id,c.player_id),))
    def freeze_wait(c):
        if(c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==BITTER
                and c.state.entities[c.event.target_id].card_id=='k81.left'):return wait(c)
        return ()
    def draw_wait(c):
        return wait(c)if c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==AUCTIONEER else()
    def discard_wait(c):
        return wait(c)if c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==CLAWS else()
    def dr_wait(c):return wait(c)
    def cancel(c):
        return(Destroy(c.state.players[3-c.player_id].weapon_id,c.source_id),)if c.event.player_id!=c.player_id else()
    for name,event,body in(('freeze_wait','frozen',freeze_wait),('draw_wait','card_drawn',draw_wait),('discard_wait','card_discarded',discard_wait),('cancel','attack_declared',cancel)):
        r.register_behavior('k81.'+name,body);r.register_card(CardDefinition('k81.'+name,name,CardType.MINION,health=20,triggers=(TriggerSpec(event,'k81.'+name),),metadata=META))
    def keeper_entry(c):
        return(AddToHand(c.player_id,'k81.dragon',c.source_id),)if c.state.entities[c.event.target_id].card_id==KEEPER else()
    def keeper_bounce(c):
        e=c.state.entities[c.event.target_id]
        if e.card_id!=KEEPER or Keyword.TAUNT not in e.keywords or Keyword.DIVINE_SHIELD in e.keywords:return ()
        return(ReturnToHand(e.id),SummonFromZone(c.player_id,zone=Zone.HAND,query=PoolQuery(kinds=(CardType.MINION,),min_cost=4,max_cost=4),selection='first',source_id=c.source_id,cause=SummonCause.capture(c)))
    for name,event,body in(('keeper_entry','minion_summoned',keeper_entry),('keeper_bounce','ability_granted',keeper_bounce)):
        r.register_behavior('k81.'+name,body);r.register_card(CardDefinition('k81.'+name,name,CardType.MINION,health=10,triggers=(TriggerSpec(event,'k81.'+name),),metadata=META))
    r.register_behavior('k81.dr_wait',dr_wait);r.register_card(CardDefinition('k81.death_wait','death wait',CardType.MINION,health=1,deathrattle='k81.dr_wait',metadata=META))
    def script(c,op):
        if op=='hurt':return(Damage(c.target_id,1,c.source_id),)
        if op=='heal':return(Heal(c.target_id,20,c.source_id),)
        if op=='silence':return(Silence(c.target_id),)
        if op=='kill':return(Destroy(c.target_id,c.source_id),)
        if op=='control':return(ChangeControl(c.target_id,c.player_id),)
        if op=='copy':return(CopyMinion(c.target_id,c.player_id),)
        if op=='armor':return()
        if op=='last_wear':return(ModifyWeapon(c.state.players[c.player_id].weapon_id,durability=-2),)
        if op=='axe_last':return(ModifyWeapon(c.state.players[c.player_id].weapon_id,durability=-1),)
        if op=='automatic':return(CastSpell(c.player_id,'k81.script_noop',source_id=c.source_id),)
        if op=='auto_targetless':return(CastSpell(c.player_id,'k81.targeted',source_id=c.source_id),)
        if op=='mark_yeti':return tuple(ModifyStoredCost(CardReference.capture(c.state.entities[i]),CostSpec(delta=4),c.source_id)
            for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==YETI)
        if op in('transform_initial','copy_initial'):
            original=set(c.state.opening.original_entities[c.player_id-1]);e=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if i in original and c.state.entities[i].card_id==YETI)
            ref=CardReference.capture(e)
            return(TransformStoredCard(ref,FIREBALL,c.source_id),)if op=='transform_initial'else(CopyCard(ref,c.player_id,source_id=c.source_id),)
        if op=='noop':return()
        raise AssertionError(op)
    for op in('hurt','heal','silence','kill','control','copy','last_wear','axe_last','automatic','auto_targetless','mark_yeti','transform_initial','copy_initial','noop'):
        key='k81.script_'+op;r.register_behavior(key,lambda c,op=op:script(c,op))
        r.register_card(CardDefinition(key,op,CardType.SPELL,on_play=key,metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if op in('hurt','heal','silence','kill','control','copy')else None))
    r.register_card(CardDefinition('k81.targeted','targeted',CardType.SPELL,on_play='k81.noop',targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy'),metadata=META))
    def boot(c):return(ChangeManaCrystals(c.player_id,10,filled=True),*(AddToHand(c.player_id,cid,c.source_id)for cid in(WAYGATE,YETI,'k81.script_transform_initial','k81.script_copy_initial')))
    r.register_behavior('k81.boot',boot);r.register_card(CardDefinition('k81.boot','boot',CardType.MINION,health=1,opening_hooks=(OpeningHook('after_mulligan','k81.boot'),),metadata=replace(META,collectible=True,rarity=Rarity.COMMON)))
    return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events']);saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')});return saved


def nodes(value,typename):
    if isinstance(value,dict):
        if str(value.get('type','')).endswith('.'+typename):yield value
        for v in value.values():yield from nodes(v,typename)
    elif isinstance(value,list):
        for v in value:yield from nodes(v,typename)


class ConditionalConsumerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=(YETI,)*10,seed=1081):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*10,mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp')),seed=seed),self.r)
    def entities(self,g,cid,p=1,zone='board'):
        s=g.state;return[s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid]
    def first(self,g,cid,p=1,zone='board'):return self.entities(g,cid,p,zone)[0]
    def play(self,g,cid,target=None,p=1):
        eid=self.first(g,cid,p,'hand').id;g.apply(PlayCard(p,eid,target));return eid
    def script(self,g,name,target=None,p=1):return self.play(g,'k81.script_'+name,target,p)
    def choose(self,g,key='keep'):q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=g.snapshot();self.assertEqual(Game.from_snapshot(saved,registry()).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
    def attack_hero(self,g,p=1):g.apply(Attack(p,g.state.players[p].hero_id,g.state.players[3-p].hero_id))
    def grouped(self,*,injure=False):
        hand=(BITTER,)+(('k81.script_hurt',)if injure else())
        g=self.game(hand,board=('k81.freeze_wait',),enemy=('k81.left','k81.middle','k81.right'))
        if injure:self.script(g,'hurt',self.first(g,'k81.middle',2).id)
        self.play(g,BITTER,self.first(g,'k81.middle',2).id);return g
    def opened(self):
        cards=('k81.boot',)+(YETI,)*11;policy=DeckPolicy('k81','cn37-k81-test','experimental',('k81.boot',YETI),deck_size=12,max_copies=12)
        g=Game.from_decks(MatchSetup(tuple(DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,cards)for _ in(1,2)),policy,'GAME_005',seed=1081,first_player=1),self.r)
        while g.state.pending_choice:q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        return g
    def test_complete_eight_roots_related_faces_and_dual_class_frost_mapping(self):
        d=load_batch();self.assertEqual(canonical_digest(d),BATCH_HASH);self.assertEqual((len(d['cards']),len(d['dependencies']),len(d['evidence_only'])),(8,0,2))
        for row in d['cards']+d['evidence_only']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual(self.r.card(BITTER).spell_school,SpellSchool.FROST)
        self.assertEqual(set(self.r.card(BITTER).metadata.classes),{CardClass.MAGE,CardClass.WARRIOR})
        self.assertEqual(set(self.r.card(CLAWS).metadata.classes),{CardClass.HUNTER,CardClass.WARLOCK})
        self.assertNotIn('TLC_101t',self.r.cards)
    def test_old1068_complete_definitions_and_default_fingerprint_preserved(self):
        old=json.loads((ROOT/'tests/fixtures/history/card-integration-20261014/k81-before/definition-digests.json').read_bytes());self.assertEqual(len(old),1068)
        self.assertEqual(old,historical_definition_digests(self.r,old))
        self.assertEqual(representative().fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)
    def test_cultist_damage_healing_and_silence_use_existing_relation(self):
        g=self.game(('k81.script_hurt','k81.script_heal','k81.script_silence'),board=(CULTIST,));e=self.first(g,CULTIST);self.assertEqual(e.attack,2)
        self.script(g,'hurt',e.id);self.assertEqual(g.state.entities[e.id].attack,5)
        self.script(g,'heal',e.id);self.assertEqual(g.state.entities[e.id].attack,2)
        self.script(g,'silence',e.id);self.assertEqual(g.state.entities[e.id].keywords,frozenset())
    def test_cultist_reborn_one_health_recomputes_damaged_attack(self):
        g=self.game(('k81.script_kill',),board=(CULTIST,));old=self.first(g,CULTIST).id;self.script(g,'kill',old)
        fresh=self.first(g,CULTIST);self.assertNotEqual(old,fresh.id);self.assertEqual((fresh.attack,fresh.health),(5,1));self.assertNotIn(Keyword.REBORN,fresh.keywords);self.portable(g)
    def test_tyrant_opponent_turn_changes_and_returns_without_attachments(self):
        g=self.game(board=(TYRANT,));e=self.first(g,TYRANT);self.assertEqual(e.attack,1);before=len(e.enchantments)
        g.apply(EndTurn(1));self.assertEqual(g.state.entities[e.id].attack,7);g.apply(EndTurn(2));self.assertEqual(g.state.entities[e.id].attack,1)
        self.assertEqual(len(g.state.entities[e.id].enchantments),before);self.portable(g)
    def test_tyrant_control_and_current_copy_derive_new_controller_turn(self):
        g=self.game(('k81.script_control','k81.script_copy'),enemy=(TYRANT,));old=self.first(g,TYRANT,2).id;self.assertEqual(g.state.entities[old].attack,7)
        self.script(g,'control',old);self.assertEqual(g.state.entities[old].attack,1);self.script(g,'copy',old)
        self.assertEqual([e.attack for e in self.entities(g,TYRANT)],[1,1])
    def test_keeper_holding_dragon_and_all_tribe_grants_both_native_keywords(self):
        for cid in('k81.dragon','k81.all'):
            with self.subTest(cid=cid):
                g=self.game((KEEPER,cid));source=self.play(g,KEEPER);self.assertEqual(g.state.entities[source].keywords,frozenset((Keyword.TAUNT,Keyword.DIVINE_SHIELD)))
                self.assertEqual(g.state.players[1].mana,36)
    def test_keeper_no_dragon_and_effect_summon_do_not_grant(self):
        g=self.game((KEEPER,YETI));source=self.play(g,KEEPER);self.assertEqual(g.state.entities[source].keywords,frozenset())
        h=self.game(('k81.dragon',),board=(KEEPER,));self.assertEqual(self.first(h,KEEPER).keywords,frozenset())
    def test_keeper_reads_hand_after_real_entry_reactions(self):
        g=self.game((KEEPER,),board=('k81.keeper_entry',));source=self.play(g,KEEPER)
        self.assertTrue(self.entities(g,'k81.dragon',zone='hand'));self.assertIn(Keyword.TAUNT,g.state.entities[source].keywords);self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[source].keywords)
    def test_keeper_second_keyword_does_not_follow_same_id_reentry(self):
        g=self.game((KEEPER,'k81.dragon'),board=('k81.keeper_bounce',));source=self.play(g,KEEPER)
        self.assertEqual(self.first(g,KEEPER).id,source);self.assertGreater(self.first(g,KEEPER).zone_epoch,1);self.assertEqual(self.first(g,KEEPER).keywords,frozenset());self.portable(g)
    def test_bitter_freezes_all_original_neighbors_and_destroys_only_injured(self):
        g=self.grouped(injure=True);middle=self.first(g,'k81.middle',2).id;self.portable(g);self.choose(g)
        self.assertEqual(g.state.entities[middle].zone,Zone.GRAVEYARD);self.assertTrue(self.first(g,'k81.left',2).frozen);self.assertTrue(self.first(g,'k81.right',2).frozen);self.portable(g)
    def test_bitter_condition_reads_original_members_after_freeze_reactions(self):
        g=self.grouped(injure=True);self.choose(g,'heal');self.assertEqual(self.first(g,'k81.middle',2).health,5)
        h=self.grouped();right=self.first(h,'k81.right',2).id;self.choose(h,'hurt');self.assertEqual(h.state.entities[right].zone,Zone.GRAVEYARD)
    def test_bitter_does_not_rebind_departed_and_resummoned_same_physical_id(self):
        g=self.grouped();right=self.first(g,'k81.right',2);self.choose(g,'bounce');fresh=self.first(g,'k81.right',2)
        self.assertEqual(fresh.id,right.id);self.assertGreater(fresh.zone_epoch,right.zone_epoch);self.assertFalse(fresh.frozen);self.portable(g)
    def test_bitter_does_not_reselect_neighbors_after_primary_replacement(self):
        g=self.grouped();middle=self.first(g,'k81.middle',2).id;self.choose(g,'replace')
        self.assertEqual(g.state.entities[middle].zone,Zone.HAND);self.assertFalse(self.first(g,YETI,2).frozen);self.assertTrue(self.first(g,'k81.right',2).frozen)
    def test_bitter_original_member_control_change_skips_further_freezing(self):
        g=self.grouped();right=self.first(g,'k81.right',2).id;self.choose(g,'control');self.assertEqual(g.state.entities[right].controller,1);self.assertFalse(g.state.entities[right].frozen)
    def test_bitter_physical_location_and_dormant_slots_do_not_skip_outward(self):
        for blocker in('k81.location',DORMANT):
            with self.subTest(blocker=blocker):
                g=self.game((BITTER,),enemy=('k81.left',blocker,'k81.middle','k81.right'))
                self.play(g,BITTER,self.first(g,'k81.middle',2).id);self.assertFalse(self.first(g,'k81.left',2).frozen)
                self.assertFalse(g.state.entities[self.first(g,blocker,2).id].frozen);self.assertTrue(self.first(g,'k81.right',2).frozen)
    def test_bitter_can_target_friendly_minion_but_not_hero(self):
        g=self.game((BITTER,),board=(YETI,));saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,BITTER,g.state.players[1].hero_id)
        self.assertEqual(g.snapshot(),saved);self.play(g,BITTER,self.first(g,YETI).id);self.assertTrue(self.first(g,YETI).frozen)
    def test_bitter_waiting_failure_rolls_back_only_choice_and_keeps_paid_root(self):
        g=self.grouped();saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.assertEqual(g.state.players[1].mana,35)
    def test_bitter_pending_codec_rejects_duplicate_future_and_foreign_group(self):
        g=self.grouped();saved=g.snapshot();self.assertTrue(list(nodes(saved,'DestroyDamagedFrozenGroup')))
        for mode in('duplicate','future','foreign','index'):
            bad=deepcopy(saved);group=next(nodes(bad,'DestroyDamagedFrozenGroup'))['fields'];members=group['members']['tuple']
            if mode=='duplicate':members[-1]=deepcopy(members[0])
            elif mode=='future':members[-1]['fields']['zone_epoch']=99999
            elif mode=='foreign':members[-1]['fields']['player_id']=1
            else:next(nodes(bad,'FreezeOriginalGroupMember'))['fields']['index']=999
            with self.subTest(mode=mode),self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),registry())
    def test_freeze_group_constructor_domains_are_explicit(self):
        ref=MinionReference(10,2,YETI,0,1)
        for members in((),(ref,ref),[ref]):
            with self.subTest(members=members),self.assertRaises(ValueError):DestroyDamagedFrozenGroup(1,1,1,ref,members)
        group=DestroyDamagedFrozenGroup(1,1,1,ref,(ref,))
        with self.assertRaises(ValueError):FreezeOriginalGroupMember(group,True)
        with self.assertRaises(ValueError):FreezeOriginalGroupMember(group,1)
    def test_axe_last_wear_still_damages_both_boards_once_and_not_heroes(self):
        g=self.game((AXE,'k81.script_axe_last'),board=(YETI,),enemy=(YETI,));weapon=self.play(g,AXE);self.script(g,'axe_last');self.attack_hero(g)
        self.assertEqual(g.state.entities[weapon].zone,Zone.GRAVEYARD);self.assertEqual(self.first(g,YETI).health,4);self.assertEqual(self.first(g,YETI,2).health,4)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28);self.portable(g)
    def test_axe_minion_attack_and_equipment_replacement_do_not_trigger(self):
        g=self.game((AXE,REPLACEMENT),board=(YETI,),enemy=(YETI,));self.play(g,AXE);self.play(g,REPLACEMENT)
        self.assertEqual(self.first(g,YETI).health,5);g.apply(Attack(1,self.first(g,YETI).id,g.state.players[2].hero_id));self.assertEqual(self.first(g,YETI).health,5)
    def test_axe_after_lethal_minion_combat_keeps_original_death_batch_and_wait(self):
        g=self.game((AXE,),board=('k81.death_wait',),enemy=('k81.fodder',));self.play(g,AXE);g.apply(Attack(1,g.state.players[1].hero_id,self.first(g,'k81.fodder',2).id))
        self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.choose(g);self.assertFalse(g.state.players[1].board);self.assertFalse(g.state.players[2].board)
    def test_claws_last_wear_discards_highest_current_hand_cost(self):
        g=self.game((CLAWS,'k81.script_last_wear',YETI,FIREBALL,'k81.script_mark_yeti'));weapon=self.play(g,CLAWS);self.script(g,'last_wear');self.script(g,'mark_yeti')
        highest=self.first(g,YETI,zone='hand').id;self.attack_hero(g);self.assertEqual(g.state.entities[highest].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[weapon].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.discard_history),1);self.portable(g)
    def test_claws_empty_hand_and_random_equal_cost_tie_are_normal(self):
        empty=self.game((CLAWS,));self.play(empty,CLAWS);self.attack_hero(empty);self.assertFalse(empty.state.discard_history)
        g=self.game((CLAWS,YETI,FIREBALL),seed=181);self.play(g,CLAWS);candidates={e.id for cid in(YETI,FIREBALL)for e in self.entities(g,cid,zone='hand')}
        self.attack_hero(g);self.assertEqual(len(g.state.discard_history),1);self.assertIn(g.state.discard_history[0].entity_id,candidates);self.portable(g)
    def test_claws_waiting_discard_restores_without_rewear_or_extra_discard(self):
        g=self.game((CLAWS,YETI),board=('k81.discard_wait',));weapon=self.play(g,CLAWS);self.attack_hero(g);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[weapon].durability,2);self.portable(g);self.choose(g);self.assertEqual(g.state.entities[weapon].durability,2);self.assertEqual(len(g.state.discard_history),1)
    def test_removed_weapon_before_delivery_has_no_listener_reward(self):
        g=self.game((CLAWS,YETI),enemy=('k81.cancel',));self.play(g,CLAWS);self.attack_hero(g)
        self.assertFalse(g.state.discard_history);self.assertEqual(g.state.character_attack_history[-1].terminal.status,'completed')
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)
    def test_auctioneer_real_prepare_uses_old_action_and_play_lock(self):
        g=self.game((AUCTIONEER,));card=self.first(g,AUCTIONEER,zone='hand').id;g.apply(UseHandAction(1,card,'prepare'));self.assertEqual(g.quote_cost(card).amount,0)
        with self.assertRaises(IllegalAction):g.apply(PlayCard(1,card))
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,AUCTIONEER);self.portable(g)
    def test_auctioneer_manual_cast_draws_once_before_payload_and_not_on_minion(self):
        g=self.game((AUCTIONEER,'k81.script_noop',YETI));self.play(g,AUCTIONEER);self.play(g,YETI);self.assertFalse(g.state.draw_history)
        self.script(g,'noop');self.assertEqual(len(g.state.draw_history),1);self.assertEqual(len(g.state.cast_history),1)
    def test_auctioneer_automatic_cast_is_not_a_second_paid_play(self):
        g=self.game(('k81.script_automatic',),board=(AUCTIONEER,));self.script(g,'automatic');self.assertEqual(len(g.state.draw_history),2)
        self.assertEqual([r.origin for r in g.state.cast_history],['hand','effect']);self.assertEqual(len(g.state.play_history),1);self.portable(g)
    def test_auctioneer_failed_targetless_automatic_attempt_is_not_extra_draw(self):
        g=self.game(('k81.script_auto_targetless',),board=(AUCTIONEER,));self.script(g,'auto_targetless')
        self.assertIsNotNone(g.state.cast_history[-1].failure);self.assertEqual(len(g.state.draw_history),1)
    def test_auctioneer_countered_hand_cast_still_has_one_real_cast_reward(self):
        g=self.game(('k81.script_noop',),board=(AUCTIONEER,),enemy_hand=('CORE_EX1_287',));g.apply(EndTurn(1));self.play(g,'CORE_EX1_287',p=2);g.apply(EndTurn(2))
        before=len(g.state.draw_history);self.script(g,'noop');self.assertEqual(len(g.state.draw_history),before+1);self.assertEqual(g.state.cast_history[-1].failure,'countered');self.portable(g)
    def test_auctioneer_enemy_spell_and_silenced_provider_do_not_draw(self):
        g=self.game(('k81.script_silence','k81.script_noop'),board=(AUCTIONEER,),enemy_hand=('k81.script_noop',))
        self.script(g,'silence',self.first(g,AUCTIONEER).id);self.assertEqual(len(g.state.draw_history),1);self.script(g,'noop');self.assertEqual(len(g.state.draw_history),1)
        g.apply(EndTurn(1));before=len(g.state.draw_history);self.script(g,'noop',p=2);self.assertEqual(len(g.state.draw_history),before)
    def test_auctioneer_draw_wait_restore_and_choice_failure_keep_one_original_cast(self):
        g=self.game(('k81.script_noop',),board=(AUCTIONEER,'k81.draw_wait'));self.script(g,'noop');self.assertIsNotNone(g.state.pending_choice);self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.assertEqual(len(g.state.draw_history),1);self.assertEqual(len(g.state.cast_history),1)
    def test_waygate_unknown_scenario_starting_identity_errors_atomically(self):
        g=self.game((WAYGATE,YETI));saved=g.snapshot()
        with self.assertRaises(ValueError):self.play(g,WAYGATE)
        self.assertEqual(g.snapshot(),saved)
    def test_waygate_uses_real_original_physical_inventory_not_card_name(self):
        g=self.opened();originals=set(g.state.opening.original_entities[0]);hand=[g.state.entities[i]for i in g.state.players[1].hand]
        generated=next(e for e in hand if e.card_id==YETI and e.id not in originals);initial=[e for e in hand if e.id in originals and e.card_id==YETI]
        self.assertTrue(initial);self.play(g,WAYGATE);self.assertEqual(g.quote_cost(generated.id).amount,3)
        self.assertTrue(all(g.quote_cost(e.id).amount==4 for e in initial));self.portable(g)
    def test_waygate_transformed_original_and_new_copy_are_actual_current_recipients(self):
        g=self.opened();self.script(g,'transform_initial');changed=next(e for e in self.entities(g,FIREBALL,zone='hand')if e.face_replaced)
        self.script(g,'copy_initial');original=set(g.state.opening.original_entities[0]);copies=[e.id for e in self.entities(g,YETI,zone='hand')if e.id not in original]
        self.assertEqual(len(copies),2);self.play(g,WAYGATE);self.assertEqual(g.quote_cost(changed.id).amount,3);self.assertTrue(all(g.quote_cost(i).amount==3 for i in copies));self.portable(g)
    def test_waygate_player_commands_do_not_expose_starting_inventory_or_private_refs(self):
        g=self.opened();self.play(g,WAYGATE)
        for player in(1,2):
            public=json.dumps(g.for_player(player).legal_actions(),ensure_ascii=False)
            for key in('original_entities','original_deck','resolution_frame','face_replaced','zone_epoch'):self.assertNotIn(key,public)
    def test_actual_schema299_default_and_constructed_snapshots_are_rejected(self):
        for name,r in(('constructed-v89-core374-schema299.json',build_registry()),('default-v65-core374-schema299.json',representative())):
            saved=json.loads((ROOT/'tests/fixtures/history/card-integration-20261014/k81-before'/name).read_bytes())
            with self.subTest(name=name),self.assertRaisesRegex(SnapshotError,'Unsupported snapshot schema version'):Game.from_snapshot(saved,r)


if __name__=='__main__':unittest.main()
