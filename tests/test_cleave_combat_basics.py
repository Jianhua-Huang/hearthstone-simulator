"""Native cleave uses one original combat exchange and current adjacency."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, CardClass, CardDefinition, CardType, EndTurn, Game,
    IllegalAction, Keyword, PlayCard, PlayerSetup, Rarity, Registry, ResolutionError,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion,
    CombatExchange, Damage, DamageBatch, Destroy, EquipWeapon, InvokeBehavior,
    RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.interrupts import RedirectAttack
from hs_sim.engine.model import AbilityInstance, DamageKind, validate_invariants
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

REAPER='GVG_113'; WEAPON='BT_271'
PATH=Path(__file__).resolve().parents[1]/'data/support/cleave-combat-basics.json'
PIN='83c5d189d414f1eaf6bd837e0154fcffdd32104aca19f6787cd738e6834a6d13'


def evidence():
    support=json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support)!=PIN:raise ValueError('Cleave evidence changed')
    for row in support['records']:
        if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Raw evidence changed')
    return {row['id']:row['data'] for row in support['records']}


def registry():
    r=Registry('isolated-cleave-combat-basics-v1');raw=evidence()
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=80,metadata=metadata()))
    for cid,attack,health,keywords,fields in (
        ('plain',2,15,(),{}),('small',1,3,(),{}),('lethal',20,15,(),{}),
        ('shield',2,15,(Keyword.DIVINE_SHIELD,),{}),('immune',2,15,(Keyword.IMMUNE,),{}),
        ('stealth',2,15,(Keyword.STEALTH,),{}),('sleeping',2,15,(),{'dormant_turns':2}),
        ('taunt',2,15,(Keyword.TAUNT,),{}),
    ):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=attack,health=health,
            keywords=keywords,metadata=metadata(),**fields))
    row=raw[REAPER]
    r.register_card(CardDefinition(REAPER,row['name'],CardType.MINION,cost=row['cost'],
        attack=row['attack'],health=row['health'],cleave=True,
        metadata=metadata(tribes=('mech',),rarity=Rarity.LEGENDARY)))
    row=raw[WEAPON]
    r.register_card(CardDefinition(WEAPON,row['name'],CardType.WEAPON,cost=row['cost'],
        attack=row['attack'],durability=row['health'],cleave=True,
        metadata=metadata(CardClass.DEMON_HUNTER,rarity=Rarity.EPIC)))
    r.register_card(CardDefinition('plain-weapon','Plain weapon',CardType.WEAPON,attack=3,durability=2,metadata=metadata()))
    def fail(c):raise ValueError('Fixture failure after combat')
    r.register_behavior('fail',fail)
    def pause(c):
        source=c.event.source_id;enemy=c.state.players[2].board
        if c.state.entities[source].card_id not in (REAPER,'hero'):return ()
        wid=dict(c.event.data)['window_id']
        return (RequestChoice(1,(
            ChoiceOption('resolve','Resolve'),
            ChoiceOption('remove-left','Remove neighbor',(Destroy(enemy[1]),)),
            ChoiceOption('redirect','Redirect',(RedirectAttack(wid,enemy[-1]),)),
            ChoiceOption('buff','Increase attack',(Buff(source,attack=2),)),
            ChoiceOption('silence','Silence',(Silence(source),)),
            ChoiceOption('remove','Remove attacker',(Destroy(source),)),
            ChoiceOption('replace-weapon','Replace weapon',(EquipWeapon(1,'plain-weapon'),)),
            ChoiceOption('fault','Change and fail',(Buff(source,attack=2),InvokeBehavior('fail',source_id=c.source_id,player_id=1))),
        ),c.source_id),)
    r.register_behavior('pause',pause)
    r.register_card(CardDefinition('watch','Watch',CardType.MINION,health=10,
        triggers=(TriggerSpec('attack_declared','pause'),),metadata=metadata()))
    r.register_card(CardDefinition('late-fail','Late fail',CardType.MINION,health=10,
        triggers=(TriggerSpec('attack_finished','fail'),),metadata=metadata()))
    # A damage observer sees every hit already settled, before any death reaction.
    def batch_observer(c):
        if c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==REAPER:
            victims=[c.state.entities[i] for i in c.state.players[2].board]
            if not all(e.damage==6 for e in victims):raise ValueError('Cleave split into sequential batches')
        return ()
    r.register_behavior('batch-observer',batch_observer)
    r.register_card(CardDefinition('batch-watch','Batch watch',CardType.MINION,health=10,
        triggers=(TriggerSpec('damage_dealt','batch-observer'),),metadata=metadata()))
    for cid,fn in (
        ('silence',lambda c:(Silence(c.target_id),)),
        ('transform',lambda c:(Transform(c.target_id,'plain'),)),
        ('bounce',lambda c:(ReturnToHand(c.target_id),)),
        ('copy',lambda c:(CopyMinion(c.target_id,1),)),
        ('base-copy',lambda c:(CopyMinion(c.target_id,1,mode='base'),)),
        ('transfer',lambda c:(ChangeControl(c.target_id,2),)),
        ('hero-buff',lambda c:(Buff(c.target_id,attack=2),)),
    ):
        r.register_behavior(cid,fn)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,requires_target=True,metadata=metadata()))
    return r


class CleaveCombatBasicsTests(unittest.TestCase):
    def game(self,enemy=('plain','plain','plain'),board=(REAPER,),hand=(),weapon=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,weapon_card_id=weapon,deck=('plain',)*5,mana=10,max_mana=10),
            PlayerSetup('hero',board=enemy,deck=('plain',)*5,mana=10,max_mana=10),
        ),seed=51),registry())
    def source(self,g):
        return next(i for i in g.state.players[1].board if g.state.entities[i].card_id==REAPER)
    def attack(self,g,index=1,source=None):
        return g.apply(Attack(1,self.source(g) if source is None else source,g.state.players[2].board[index]))
    def play(self,g,cid,target):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        return g.apply(PlayCard(1,eid,target))
    def choose(self,g,key='resolve'):
        c=g.state.pending_choice;return g.apply(SelectChoice(c.player_id,c.id,(key,)))
    def check(self,g):
        snap=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap,registry()).snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),snap)
    def damages(self,g,ids):return [g.state.entities[i].damage for i in ids]

    def test_complete_real_sources_and_native_minion_weapon_declarations(self):
        raw=evidence();r=registry()
        self.assertEqual([(raw[c]['dbf_id'],raw[c]['cost'],raw[c]['attack'],raw[c]['health']) for c in (REAPER,WEAPON)],[(2081,8,6,9),(56905,7,5,3)])
        self.assertEqual((r.card(REAPER).cleave,r.card(WEAPON).cleave),(True,True))
        self.assertEqual(r.card(REAPER).metadata.tribes,('mech',))

    def test_middle_cleave_only_primary_retaliates_and_one_attack_is_consumed(self):
        g=self.game();ids=list(g.state.players[2].board);source=self.source(g);self.attack(g)
        self.assertEqual(self.damages(g,ids),[6,6,6]);self.assertEqual(g.state.entities[source].damage,2)
        self.assertEqual(g.state.entities[source].attacks_this_turn,1)
        self.assertEqual(sum(e.kind=='attack_declared' for e in g.events),1)
        self.assertEqual(sum(e.kind=='attack_finished' for e in g.events),1)
        with self.assertRaises(IllegalAction):self.attack(g)
        self.check(g)

    def test_board_edges_and_single_target_do_not_wrap_or_duplicate(self):
        for enemy,index,expected in ((('plain',)*4,0,[6,6,0,0]),(('plain',)*4,3,[0,0,6,6]),(('plain',),0,[6])):
            with self.subTest(index=index):
                g=self.game(enemy=enemy);ids=list(g.state.players[2].board);self.attack(g,index)
                self.assertEqual(self.damages(g,ids),expected)

    def test_hero_defender_has_no_board_neighbors(self):
        g=self.game();ids=list(g.state.players[2].board);hero=g.state.players[2].hero_id
        g.apply(Attack(1,self.source(g),hero))
        self.assertEqual(g.state.entities[hero].damage,6);self.assertEqual(self.damages(g,ids),[0,0,0])

    def test_adjacent_shield_and_immunity_use_original_damage_prevention(self):
        g=self.game(enemy=('shield','plain','immune'));ids=list(g.state.players[2].board);self.attack(g)
        self.assertEqual(self.damages(g,ids),[0,6,0])
        self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[ids[0]].keywords)
        self.check(g)

    def test_adjacent_stealth_is_not_an_attack_target(self):
        g=self.game(enemy=('stealth','taunt','plain'));ids=list(g.state.players[2].board);self.attack(g)
        self.assertEqual(self.damages(g,ids),[6,6,6])
        self.assertEqual(g.state.entities[self.source(g)].damage,2)

    def test_dormant_physical_slot_blocks_distant_neighbor(self):
        g=self.game(enemy=('plain','sleeping','plain','plain'));ids=list(g.state.players[2].board);self.attack(g,2)
        self.assertEqual(self.damages(g,ids),[0,0,6,6])

    def test_all_hits_settle_before_damage_observers(self):
        g=self.game(board=(REAPER,'batch-watch'));self.attack(g);self.check(g)

    def test_dead_attacker_still_delivers_all_prepared_outgoing_hits(self):
        g=self.game(enemy=('small','lethal','small'));ids=list(g.state.players[2].board);source=self.source(g)
        self.attack(g)
        self.assertEqual(self.damages(g,ids),[6,6,6]);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual([g.state.entities[i].zone for i in (ids[0],ids[2])],[Zone.GRAVEYARD]*2)
        self.assertEqual(len({r.batch for r in g.state.death_history}),1)
        self.check(g)

    def test_weapon_cleave_uses_total_hero_attack_and_one_durability(self):
        g=self.game(board=(),hand=('hero-buff',),weapon=WEAPON);hero=g.state.players[1].hero_id
        self.play(g,'hero-buff',hero);ids=list(g.state.players[2].board);weapon=g.state.players[1].weapon_id
        self.attack(g,source=hero)
        self.assertEqual(self.damages(g,ids),[7,7,7]);self.assertEqual(g.state.entities[hero].damage,2)
        self.assertEqual(g.state.entities[weapon].durability,2)
        self.check(g)

    def test_attacked_cleave_minion_does_not_cleave_in_retaliation(self):
        g=self.game(board=('plain','plain','plain'),enemy=(REAPER,));ids=list(g.state.players[1].board)
        self.attack(g,0,ids[1]);self.assertEqual(self.damages(g,ids),[0,6,0]);self.check(g)

    def test_plain_weapon_remains_single_target(self):
        g=self.game(board=(),weapon='plain-weapon');ids=list(g.state.players[2].board)
        self.attack(g,source=g.state.players[1].hero_id);self.assertEqual(self.damages(g,ids),[0,3,0])

    def test_silence_and_transform_remove_native_cleave(self):
        for cid,damage in (('silence',6),('transform',2)):
            with self.subTest(cid=cid):
                g=self.game(hand=(cid,));source=self.source(g);self.play(g,cid,source);ids=list(g.state.players[2].board)
                self.attack(g,source=source);self.assertEqual(self.damages(g,ids),[0,damage,0]);self.check(g)

    def test_return_to_hand_replay_reinstalls_printed_cleave(self):
        g=self.game(hand=('silence','bounce'));source=self.source(g)
        self.play(g,'silence',source);self.play(g,'bounce',source);g.apply(PlayCard(1,source))
        g.apply(EndTurn(1));g.apply(EndTurn(2));ids=list(g.state.players[2].board);self.attack(g)
        self.assertEqual(self.damages(g,ids),[6,6,6]);self.check(g)

    def test_current_and_base_copies_keep_native_cleave_and_attack_later(self):
        for cid in ('copy','base-copy'):
            with self.subTest(cid=cid):
                g=self.game(hand=(cid,));self.play(g,cid,self.source(g));copy=g.state.players[1].board[-1]
                g.apply(EndTurn(1));g.apply(EndTurn(2));ids=list(g.state.players[2].board);self.attack(g,source=copy)
                self.assertEqual(self.damages(g,ids),[6,6,6]);self.check(g)

    def test_control_transfer_uses_new_enemy_board_after_turn_change(self):
        g=self.game(board=(REAPER,'plain','plain','plain'),hand=('transfer',));source=self.source(g)
        self.play(g,'transfer',source);g.apply(EndTurn(1));ids=list(g.state.players[1].board)
        g.apply(Attack(2,source,ids[1]));self.assertEqual(self.damages(g,ids),[6,6,6]);self.check(g)

    def test_waiting_neighbor_removed_is_recomputed_before_damage(self):
        g=self.game(enemy=('plain',)*5,board=(REAPER,'watch'));ids=list(g.state.players[2].board)
        self.attack(g,2);self.assertIsNotNone(g.state.pending_choice);self.check(g)
        restored=Game.from_snapshot(g.snapshot(),registry());self.choose(g,'remove-left');self.choose(restored,'remove-left')
        self.assertEqual(self.damages(g,ids),[6,0,6,6,0]);self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)

    def test_redirected_target_determines_cleave_neighbors(self):
        g=self.game(enemy=('plain',)*4,board=(REAPER,'watch'));ids=list(g.state.players[2].board)
        self.attack(g);self.choose(g,'redirect');self.assertEqual(self.damages(g,ids),[0,0,6,6]);self.check(g)

    def test_waiting_current_attack_and_silence_are_read_at_delivery(self):
        for key,expected in (('buff',[8,8,8]),('silence',[0,6,0])):
            with self.subTest(key=key):
                g=self.game(board=(REAPER,'watch'));ids=list(g.state.players[2].board);self.attack(g)
                restored=Game.from_snapshot(g.snapshot(),registry());self.choose(g,key);self.choose(restored,key)
                self.assertEqual(self.damages(g,ids),expected);self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)

    def test_removed_attacker_cancels_all_cleave_hits(self):
        g=self.game(board=(REAPER,'watch'));ids=list(g.state.players[2].board);self.attack(g);self.choose(g,'remove')
        self.assertEqual(self.damages(g,ids),[0,0,0]);self.check(g)

    def test_immediate_and_waiting_failure_roll_back_complete_combat(self):
        g=self.game(board=(REAPER,'late-fail'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.attack(g)
        self.assertEqual(g.snapshot(),before)
        g=self.game(board=(REAPER,'watch'));self.attack(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.check(g)

    def test_declaration_and_native_instance_reject_arbitrary_grants(self):
        card=registry().card(REAPER)
        for fields in ({'cleave':1},{'cleave':None},{'kind':CardType.HERO},{'kind':CardType.SPELL},{'keywords':(Keyword.MAGNETIC,)}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):Registry('bad').register_card(replace(card,**fields))
        a=AbilityInstance(1,'cleave',source_id=2,origin='printed')
        for fields in ({'origin':'granted'},{'source_id':None},{'consumed':True},{'expires_turn':1},{'remove_on_silence':False},{'magnetic_id':3},{'attack':2}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):replace(a,**fields)

    def test_native_carrier_rejects_duplicate_or_wrong_face(self):
        g=self.game();state=g.state;e=state.entities[self.source(g)];a=next(a for a in e.abilities if a.kind=='cleave')
        e.abilities.append(replace(a,id=state.next_attachment_id));state.next_attachment_id+=1
        with self.assertRaises(ValueError):validate_invariants(state,g.registry)
        state=g.state;e=state.entities[state.players[2].board[0]]
        e.abilities.append(AbilityInstance(state.next_attachment_id,'cleave',source_id=e.id,origin='printed'));state.next_attachment_id+=1
        with self.assertRaises(ValueError):validate_invariants(state,g.registry)

    def test_player_queries_are_pure_and_do_not_expose_native_wire_state(self):
        g=self.game(hand=('bounce',));before=g.snapshot()
        for player in (1,2):
            for _ in range(2):
                observation=g.for_player(player).observe();actions=g.for_player(player).legal_actions()
                text=json.dumps((observation,actions),ensure_ascii=False)
                for key in ('abilities','work_queue','rng_state','source_sha256'):self.assertNotIn('"'+key+'"',text)
        self.assertEqual(g.snapshot(),before)

    def test_version_guard_rejects_previous_and_future_schema(self):
        g=self.game();self.assertEqual(g.snapshot()['schema_version'],266)
        for version in (189,217,True):
            snap=g.snapshot();snap['schema_version']=version
            with self.assertRaises(SnapshotError):Game.from_snapshot(snap,registry())

    def test_weapon_replacement_during_wait_uses_current_native_provider(self):
        g=self.game(board=('watch',),weapon=WEAPON);hero=g.state.players[1].hero_id
        ids=list(g.state.players[2].board);old=g.state.players[1].weapon_id;self.attack(g,source=hero)
        self.check(g);self.choose(g,'replace-weapon')
        self.assertEqual(self.damages(g,ids),[0,3,0])
        self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[g.state.players[1].weapon_id].durability,1);self.check(g)

    def test_last_weapon_durability_still_delivers_all_hits_once(self):
        g=self.game(board=(),weapon=WEAPON);hero=g.state.players[1].hero_id;weapon=g.state.players[1].weapon_id
        for _ in range(2):
            g.apply(Attack(1,hero,g.state.players[2].hero_id));g.apply(EndTurn(1));g.apply(EndTurn(2))
        ids=list(g.state.players[2].board);self.attack(g,source=hero)
        self.assertEqual(self.damages(g,ids),[5,5,5]);self.assertIsNone(g.state.players[1].weapon_id)
        self.assertEqual(g.state.entities[weapon].zone,Zone.GRAVEYARD);self.check(g)

    def test_forged_or_truncated_combat_extras_are_rejected(self):
        from hs_sim.engine.cleave import validate_combat_hits
        g=self.game(enemy=('plain',)*4);state=g.state;a=self.source(g);ids=list(state.players[2].board)
        first=(Damage(ids[1],6,a,DamageKind.COMBAT),Damage(a,2,ids[1],DamageKind.COMBAT));combat=CombatExchange(a,ids[1])
        for extras in ((),(Damage(ids[0],6,a,DamageKind.COMBAT),),(Damage(ids[0],6,a,DamageKind.COMBAT),Damage(ids[3],6,a,DamageKind.COMBAT))):
            with self.subTest(extras=extras),self.assertRaises(ValueError):validate_combat_hits(state,DamageBatch(first+extras,combat))
        for hit in (Damage(ids[0],6,ids[1],DamageKind.COMBAT),Damage(ids[0],5,a,DamageKind.COMBAT),Damage(ids[1],6,a,DamageKind.COMBAT)):
            with self.subTest(hit=hit),self.assertRaises(ValueError):DamageBatch(first+(hit,),combat)

    def test_death_record_checks_native_cleave_face(self):
        g=self.game(enemy=('small','lethal','small'));self.attack(g);state=g.state
        index=next(i for i,r in enumerate(state.death_history) if r.card_id=='small')
        record=state.death_history[index]
        a=AbilityInstance(state.next_attachment_id,'cleave',source_id=record.entity_id,origin='printed')
        state.next_attachment_id+=1
        state.death_history[index]=replace(record,abilities=record.abilities+(a,))
        with self.assertRaises(ValueError):validate_invariants(state,g.registry)
