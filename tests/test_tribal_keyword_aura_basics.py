"""One native Rhino aura uses the shared current-tribe and Charge mechanisms."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, CardClass, CardDefinition, CardType, ChangeMinionTribes,
    EndTurn, Game, GrantKeywordAura, IllegalAction, Keyword, KeywordAuraSpec, PlayCard,
    PlayerSetup, Rarity, Registry, ResolutionError, Scenario, SelectChoice, SnapshotError,
    TribeChangeSpec, TriggerSpec, Zone, has_any_tribe)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Damage, DamageBatch,
    Destroy, GainArmor, GrantKeyword, InvokeBehavior, RequestChoice, ReturnToHand, Silence,
    Summon, Transform)
from hs_sim.engine.keyword_auras import validate_carrier
from hs_sim.engine.registry import RuleContext, UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

RHINO = 'DS1_178'
PATH = Path(__file__).resolve().parents[1] / 'data/support/tribal-keyword-aura-basics.json'
PIN = '2eb62aeeaaf6b0935569cc1c324265a7788be688c56dc2d30b220be224244ba2'
AURA = KeywordAuraSpec(Keyword.CHARGE, 'friendly_minions', include_self=True, tribes_any=('beast',))


def evidence():
    support = json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support) != PIN: raise ValueError('Tribal keyword evidence changed')
    for row in support['records']:
        if canonical_digest(row['data']) != row['data_sha256']: raise ValueError('Raw card evidence changed')
    return support['records'][0]['data']


def registry():
    r = Registry('isolated-tribal-keyword-aura-basics-v1'); raw = evidence()
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=80, metadata=metadata()))
    r.register_card(CardDefinition(RHINO, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], keyword_auras=(AURA,),
        metadata=metadata(CardClass.HUNTER, tribes=('beast',), rarity=Rarity.FREE)))
    for cid, tribes in (('beast', ('beast',)), ('plain', ()), ('dual', ('beast','undead')),
                       ('all', ('all',)), ('unknown', None)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=2, health=10,
            metadata=metadata(tribes=tribes)))
    r.register_card(CardDefinition('intrinsic', 'Intrinsic Charge', CardType.MINION, attack=2,
        health=10, keywords=(Keyword.CHARGE,), metadata=metadata(tribes=('beast',))))
    r.register_behavior('noop', lambda c: ())
    r.register_card(CardDefinition('site', 'Site', CardType.LOCATION, durability=2,
        on_use='noop', metadata=metadata()))
    r.register_card(CardDefinition('dormant', 'Dormant', CardType.MINION, attack=2, health=10,
        dormant_turns=None, metadata=metadata(tribes=('beast',))))

    def wait(c):
        source = next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == RHINO)
        return (RequestChoice(c.player_id, (
            ChoiceOption('silence', 'Silence source', (Silence(source),)),
            ChoiceOption('fault', 'Remove then fail', (Silence(source),
                InvokeBehavior('late-fault', source_id=c.source_id, player_id=c.player_id))),
        ), c.source_id),)

    def declared(c):
        if c.event.player_id != c.player_id: return ()
        return wait(c)

    def quote(c):
        target = c.state.entities[c.event.target_id]
        return (GainArmor(c.player_id, int(Keyword.CHARGE in target.keywords)),)

    def fail(c): raise ValueError('Fixture late failure')
    r.register_behavior('wait', wait); r.register_behavior('declared', declared)
    r.register_behavior('quote', quote); r.register_behavior('late-fault', fail)
    r.register_card(CardDefinition('watcher', 'Watcher', CardType.MINION, health=10,
        triggers=(TriggerSpec('attack_declared','declared'),), metadata=metadata(tribes=())))
    r.register_card(CardDefinition('observer', 'Observer', CardType.MINION, health=10,
        triggers=(TriggerSpec('tribes_changed','quote'),), metadata=metadata(tribes=())))
    targeted = {
        'silence': lambda c: (Silence(c.target_id),),
        'destroy': lambda c: (Destroy(c.target_id,c.source_id),),
        'bounce': lambda c: (ReturnToHand(c.target_id),),
        'plain-face': lambda c: (Transform(c.target_id,'plain'),),
        'rhino-face': lambda c: (Transform(c.target_id,RHINO),),
        'steal': lambda c: (ChangeControl(c.target_id,2),),
        'return': lambda c: (ChangeControl(c.target_id,1),),
        'copy': lambda c: (CopyMinion(c.target_id,1),),
        'base-copy': lambda c: (CopyMinion(c.target_id,1,mode='base'),),
        'sleep': lambda c: (MakeDormant(c.target_id,None),),
        'permanent': lambda c: (GrantKeyword(c.target_id,Keyword.CHARGE),),
        'fault': lambda c: (Silence(c.target_id), InvokeBehavior('late-fault', source_id=c.source_id,player_id=c.player_id)),
    }
    for name, op, tribes in (('add-beast','add',('beast',)), ('remove-beast','remove',('beast',)),
                             ('set-beast','set',('beast',)), ('set-plain','set',())):
        def work(c, op=op, tribes=tribes):
            return (ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),
                TribeChangeSpec(op,tribes),c.source_id),)
        targeted[name]=work
    scripts = {
        'wait': wait,
        'wake': lambda c: (AwakenMinion(next(i for i in c.state.players[1].board
            if c.state.entities[i].dormancy is not None)),),
        'summon-beast': lambda c: (Summon(1,'beast'),),
        'summon-rhino': lambda c: (Summon(1,RHINO),),
        'summon-unknown': lambda c: (Summon(1,'unknown'),),
        'kill-all': lambda c: (DamageBatch(tuple(Damage(i,100,c.source_id) for i in c.state.players[1].board)),),
    }
    for name, body in {**scripts, **targeted}.items():
        if name != 'wait': r.register_behavior(name, body)
        r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,
            requires_target=name in targeted,metadata=metadata()))
    return r


class TribalKeywordAuraBasicsTests(unittest.TestCase):
    def game(self, hand=(), board=(RHINO,'beast','plain'), enemy=('plain',), enemy_hand=(), deck=('beast',)*4):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=deck,mana=10,max_mana=10),
            PlayerSetup('hero',hand=enemy_hand,board=enemy,deck=('plain',)*4,mana=10,max_mana=10),
        ),seed=37),registry())
    def source(self,g): return g.state.players[1].board[0]
    def recipient(self,g): return g.state.players[1].board[1]
    def hero(self,g,player=2): return g.state.entities[g.state.players[player].hero_id]
    def play(self,g,cid,target=None):
        p=g.state.active_player;eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,eid,target if g.registry.card(cid).requires_target else None));return eid
    def charge(self,g,eid,expected=True): self.assertEqual(Keyword.CHARGE in g.state.entities[eid].keywords,expected)
    def choose(self,g,key):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(key,)))
    def roundtrip(self,g):
        snap=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap,registry()).snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),snap)
    def rehash(self,snap):
        snap['state_hash']=canonical_hash({k:v for k,v in snap.items() if k not in
            ('schema_version','events','events_hash','state_hash')});return snap

    def test_complete_raw_pin_and_reference_charge_is_not_intrinsic(self):
        raw=evidence();self.assertEqual((raw['id'],raw['cost'],raw['attack'],raw['health']), (RHINO,5,2,5))
        self.assertEqual(raw['text_en'],'Your Beasts have <b>Charge</b>.')
        self.assertEqual((raw['tags']['CLASS'],raw['tags']['CARDRACE'],raw['tags']['RARITY']),(3,20,2))
        card=registry().card(RHINO);self.assertEqual(card.keyword_auras,(AURA,))
        self.assertNotIn(Keyword.CHARGE,card.keywords);self.assertEqual(card.metadata.rarity,Rarity.FREE)

    def test_selector_is_immutable_unique_and_closed_to_native_board_charge(self):
        self.assertEqual(KeywordAuraSpec(Keyword.CHARGE,'friendly_minions').tribes_any,())
        with self.assertRaises(FrozenInstanceError): AURA.tribes_any=()
        for tribes in (['beast'],('beast','beast'),(True,),('',),None):
            with self.subTest(tribes=tribes),self.assertRaises((ValueError,TypeError)): replace(AURA,tribes_any=tribes)
        for kw in ({'keyword':Keyword.TAUNT},{'target':'friendly_hero'},{'target':'friendly_hand_minions'},
                   {'adjacent_only':True,'include_self':False},{'condition':'controller_has_weapon'}):
            with self.subTest(kw=kw),self.assertRaises(ValueError): replace(AURA,**kw)

    def test_native_definition_and_optional_grant_guards(self):
        card=registry().card(RHINO)
        for kw in ({'kind':CardType.HERO},{'keywords':(Keyword.MAGNETIC,)},
                   {'keywords':(Keyword.STARSHIP_PIECE,)},{'keyword_auras':(AURA,AURA)}):
            with self.subTest(kw=kw),self.assertRaises(ValueError): Registry('bad').register_card(replace(card,**kw))
        with self.assertRaises(ValueError): GrantKeywordAura(3,AURA)

    def test_current_beasts_only_include_source_and_exclude_enemy_hero_hand_deck(self):
        g=self.game(hand=('beast',),enemy=('beast',));ids=g.state.players[1].board
        self.charge(g,ids[0]);self.charge(g,ids[1]);self.charge(g,ids[2],False)
        for eid in (self.hero(g,1).id,self.hero(g).id,*g.state.players[2].board,*g.state.players[1].hand,*g.state.players[1].deck):
            self.charge(g,eid,False)
        self.assertEqual(g.state.entities[ids[1]].aura_keywords,{Keyword.CHARGE})
        self.assertFalse(g.state.entities[ids[1]].abilities);self.roundtrip(g)

    def test_dual_and_all_tribe_recipient_matching(self):
        g=self.game(board=(RHINO,'dual','all','plain'))
        for eid in g.state.players[1].board[:3]: self.charge(g,eid)
        self.charge(g,g.state.players[1].board[3],False)

    def test_all_tribe_exclusion_and_add_back_change_matching(self):
        g=self.game(board=(RHINO,'all'),hand=('remove-beast','add-beast'));eid=self.recipient(g)
        self.play(g,'remove-beast',eid);self.charge(g,eid,False)
        self.play(g,'add-beast',eid);self.charge(g,eid);self.roundtrip(g)

    def test_current_identity_set_and_remove_do_not_change_printed_metadata(self):
        g=self.game(hand=('set-beast','remove-beast'),board=(RHINO,'plain'));eid=self.recipient(g)
        self.play(g,'set-beast',eid);self.charge(g,eid)
        self.assertFalse(has_any_tribe(g.registry,g.state.entities[eid],('beast',),basis='printed'))
        self.play(g,'remove-beast',eid);self.charge(g,eid,False)

    def test_source_can_lose_own_tribe_without_losing_its_aura(self):
        g=self.game(hand=('set-plain',));src=self.source(g);target=self.recipient(g)
        self.play(g,'set-plain',src);self.charge(g,src,False);self.charge(g,target);self.roundtrip(g)

    def test_unknown_tribe_is_explicit_error_when_aura_reaches_it(self):
        with self.assertRaises(UnsupportedDefinitionError): self.game(board=(RHINO,'unknown'))

    def test_unknown_summon_rolls_back_entire_action(self):
        g=self.game(hand=('summon-unknown',));before=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'summon-unknown')
        self.assertEqual(g.snapshot(),before)

    def test_no_active_aura_does_not_invent_unknown_tribe_knowledge(self):
        g=self.game(board=('unknown',));self.charge(g,self.source(g),False);self.roundtrip(g)

    def test_real_manual_source_gets_charge_and_attacks_immediately(self):
        g=self.game(board=(),hand=(RHINO,));eid=self.play(g,RHINO)
        self.charge(g,eid);self.assertEqual(g.state.entities[eid].summoned_turn,g.state.turn)
        g.apply(Attack(1,eid,self.hero(g).id));self.assertEqual(self.hero(g).health,78);self.roundtrip(g)

    def test_real_manual_recipient_and_nonbeast_keep_distinct_summoning_rules(self):
        g=self.game(board=(RHINO,),hand=('beast','plain'));beast=self.play(g,'beast');plain=self.play(g,'plain')
        g.apply(Attack(1,beast,self.hero(g).id))
        with self.assertRaises(IllegalAction): g.apply(Attack(1,plain,self.hero(g).id))
        self.assertEqual(self.hero(g).health,78)

    def test_summoned_recipient_gets_charge_without_permanent_attachment(self):
        g=self.game(board=(RHINO,),hand=('summon-beast',));self.play(g,'summon-beast');eid=self.recipient(g)
        self.assertEqual(g.state.entities[eid].abilities,[]);g.apply(Attack(1,eid,self.hero(g).id));self.roundtrip(g)

    def test_summoned_native_source_uses_same_profile(self):
        g=self.game(board=(),hand=('summon-rhino',));self.play(g,'summon-rhino');self.charge(g,self.source(g));self.roundtrip(g)

    def test_loss_revokes_new_recipient_attack_eligibility(self):
        g=self.game(board=(RHINO,),hand=('beast','silence'));eid=self.play(g,'beast')
        self.play(g,'silence',self.source(g));self.charge(g,eid,False)
        with self.assertRaises(IllegalAction): g.apply(Attack(1,eid,self.hero(g).id))

    def test_mature_recipient_can_attack_after_aura_is_lost(self):
        g=self.game(hand=('silence',));eid=self.recipient(g);self.play(g,'silence',self.source(g))
        g.apply(Attack(1,eid,self.hero(g).id));self.assertEqual(self.hero(g).health,78)

    def test_loss_and_reacquisition_do_not_refund_spent_attack(self):
        g=self.game(board=(RHINO,'beast'),hand=('sleep','wake'));eid=self.recipient(g)
        g.apply(Attack(1,eid,self.hero(g).id));self.play(g,'sleep',self.source(g));self.charge(g,eid,False)
        self.play(g,'wake',self.source(g));self.charge(g,eid)
        self.assertEqual(g.state.entities[eid].attacks_this_turn,1)
        with self.assertRaises(IllegalAction): g.apply(Attack(1,eid,self.hero(g).id))

    def test_two_sources_remove_only_their_own_contribution(self):
        g=self.game(board=(RHINO,'beast',RHINO),hand=('silence','destroy'));eid=self.recipient(g)
        self.play(g,'silence',self.source(g));self.charge(g,eid)
        self.play(g,'destroy',g.state.players[1].board[2]);self.charge(g,eid,False);self.roundtrip(g)

    def test_intrinsic_and_old_permanent_charge_union_survive_source_loss(self):
        g=self.game(board=(RHINO,'beast','intrinsic'),hand=('permanent','silence'));eid=self.recipient(g)
        self.play(g,'permanent',eid);self.play(g,'silence',self.source(g))
        self.charge(g,eid);self.charge(g,g.state.players[1].board[2]);self.assertEqual(g.state.entities[eid].aura_keywords,set())

    def test_silencing_recipient_keeps_external_charge(self):
        g=self.game(hand=('silence',));eid=self.recipient(g);self.play(g,'silence',eid)
        self.charge(g,eid);self.assertTrue(g.state.entities[eid].silenced);self.roundtrip(g)

    def test_silencing_dynamic_recipient_restores_printed_nonbeast(self):
        g=self.game(board=(RHINO,'plain'),hand=('add-beast','silence'));eid=self.recipient(g)
        self.play(g,'add-beast',eid);self.play(g,'silence',eid);self.charge(g,eid,False)

    def test_source_bounce_and_replay_install_new_attachment_identity(self):
        g=self.game(hand=('bounce',));src=self.source(g);eid=self.recipient(g)
        old=next(a for a in g.state.entities[src].abilities if a.kind=='keyword_aura')
        self.play(g,'bounce',src);self.charge(g,eid,False);self.charge(g,src,False)
        self.play(g,RHINO);new=next(a for a in g.state.entities[src].abilities if a.kind=='keyword_aura')
        self.assertNotEqual(old.id,new.id);self.charge(g,eid);self.roundtrip(g)

    def test_source_transform_away_and_into_rhino_changes_contribution(self):
        g=self.game(hand=('plain-face','rhino-face'));src=self.source(g);eid=self.recipient(g)
        self.play(g,'plain-face',src);self.charge(g,eid,False)
        self.play(g,'rhino-face',src);self.charge(g,eid);self.roundtrip(g)

    def test_current_source_copy_has_independent_native_attachment(self):
        g=self.game(hand=('copy','silence'));src=self.source(g);eid=self.recipient(g)
        old=next(a for a in g.state.entities[src].abilities if a.kind=='keyword_aura')
        self.play(g,'copy',src);copy=g.state.entities[g.state.players[1].board[-1]]
        new=next(a for a in copy.abilities if a.kind=='keyword_aura')
        self.assertNotEqual(old.id,new.id);self.assertEqual(new.source_id,old.source_id)
        self.play(g,'silence',src);self.charge(g,eid);self.roundtrip(g)

    def test_recipient_copy_does_not_copy_external_charge_as_intrinsic(self):
        g=self.game(hand=('copy','destroy'));self.play(g,'copy',self.recipient(g));copy=g.state.entities[g.state.players[1].board[-1]]
        self.assertEqual(copy.abilities,[]);self.play(g,'destroy',self.source(g));self.charge(g,copy.id,False)

    def test_current_recipient_copy_preserves_current_tribes_base_copy_does_not(self):
        g=self.game(board=(RHINO,'plain'),hand=('add-beast','copy','base-copy'));eid=self.recipient(g)
        self.play(g,'add-beast',eid);self.play(g,'copy',eid);current=g.state.players[1].board[-1]
        self.play(g,'base-copy',eid);base=g.state.players[1].board[-1]
        self.charge(g,current);self.charge(g,base,False);self.roundtrip(g)

    def test_source_control_uses_current_controller_and_recipient_reentry(self):
        g=self.game(hand=('steal','return'),enemy=('beast',));src=self.source(g);eid=self.recipient(g)
        self.play(g,'steal',src);self.charge(g,eid,False);self.charge(g,g.state.players[2].board[0])
        self.play(g,'return',src);self.charge(g,eid);self.charge(g,g.state.players[2].board[0],False);self.roundtrip(g)

    def test_recipient_control_uses_destination_aura(self):
        g=self.game(hand=('steal',),enemy=(RHINO,));eid=self.recipient(g)
        self.play(g,'steal',eid);self.charge(g,eid);self.roundtrip(g)

    def test_source_dormancy_and_wake_share_existing_active_policy(self):
        g=self.game(hand=('sleep','wake'));src=self.source(g);eid=self.recipient(g)
        self.play(g,'sleep',src);self.charge(g,eid,False)
        self.play(g,'wake',src);self.charge(g,eid);self.roundtrip(g)

    def test_dormant_recipients_and_location_slots_are_excluded(self):
        g=self.game(board=(RHINO,'dormant','site'),hand=('wake',));eid=self.recipient(g)
        self.charge(g,eid,False);self.charge(g,g.state.players[1].board[2],False)
        self.play(g,'wake',eid);self.charge(g,eid);self.roundtrip(g)

    def test_simultaneous_death_freezes_old_charge_and_clears_live_contribution(self):
        g=self.game(board=(RHINO,'beast'),hand=('kill-all',));self.play(g,'kill-all')
        records=g.state.death_history;self.assertEqual(len(records),2)
        self.assertTrue(all(Keyword.CHARGE in d.keywords for d in records));self.roundtrip(g)

    def test_tribe_change_event_context_already_has_current_aura(self):
        g=self.game(board=(RHINO,'plain','observer'),hand=('add-beast','remove-beast'));eid=self.recipient(g)
        self.play(g,'add-beast',eid);self.assertEqual(self.hero(g,1).armor,1)
        self.play(g,'remove-beast',eid);self.assertEqual(self.hero(g,1).armor,1);self.roundtrip(g)

    def test_actual_declared_attack_wait_restores_and_uses_original_acceptance(self):
        g=self.game(board=(RHINO,'watcher'),hand=('beast',));eid=self.play(g,'beast')
        g.apply(Attack(1,eid,self.hero(g).id));self.assertIsNotNone(g.state.pending_choice);self.roundtrip(g)
        matches=(g,Game.from_snapshot(g.snapshot(),registry()),g.clone(),replay(build_replay(g),registry()))
        for match in matches:
            self.choose(match,'silence');self.charge(match,eid,False)
            self.assertEqual(self.hero(match).health,78);self.assertEqual(match.state.entities[eid].attacks_this_turn,1)
        self.assertTrue(all(m.snapshot()==g.snapshot() for m in matches));self.roundtrip(g)

    def test_choice_and_immediate_failures_roll_back_aura_and_information(self):
        g=self.game(hand=('fault','wait'));before=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'fault',self.source(g))
        self.assertEqual(g.snapshot(),before);self.play(g,'wait');before=g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.roundtrip(g)

    def test_player_queries_are_pure_and_hide_internal_selector(self):
        g=self.game(hand=('beast',));before=g.snapshot()
        for _ in range(3):
            text=json.dumps((g.observe(1),g.legal_actions(),g.player_events(1)),ensure_ascii=False,default=str)
            for hidden in ('tribes_any','keyword_aura','attachment_id','resolution_frame','registry_fingerprint'):
                self.assertNotIn(hidden,text)
        self.assertEqual(g.snapshot(),before)

    def test_native_ability_alterations_and_duplicate_instances_are_rejected(self):
        g=self.game();src=g.state.entities[self.source(g)]
        ability=next(a for a in src.abilities if a.kind=='keyword_aura')
        for kw in ({'origin':'granted'},{'expires_turn':1},{'consumed':True},
                   {'remove_on_silence':False},{'magnetic_id':1}):
            with self.subTest(kw=kw),self.assertRaises(ValueError): replace(ability,**kw)
        for spec in (replace(AURA,tribes_any=()),replace(AURA,tribes_any=('dragon',)),replace(AURA,include_self=False)):
            with self.subTest(spec=spec),self.assertRaises(ValueError):
                validate_carrier(g.registry,RHINO,CardType.MINION,[replace(ability,keyword_aura=spec)])
        with self.assertRaises(ValueError): validate_carrier(g.registry,RHINO,CardType.MINION,[ability,replace(ability,id=999)])

    def test_snapshot_selector_full_fields_and_cache_tampering_rejected(self):
        g=self.game();src=self.source(g);eid=self.recipient(g)
        for values in (None,'beast',['beast','beast'],[True],[],['dragon']):
            snap=g.snapshot();row=next(a for a in snap['state']['entities'][str(src)]['abilities'] if a['kind']=='keyword_aura')
            row['keyword_aura']['tribes_any']=values
            with self.subTest(values=values),self.assertRaises(SnapshotError): Game.from_snapshot(self.rehash(snap),registry())
        snap=g.snapshot();del next(a for a in snap['state']['entities'][str(src)]['abilities'] if a['kind']=='keyword_aura')['keyword_aura']['tribes_any']
        with self.assertRaises(SnapshotError): Game.from_snapshot(self.rehash(snap),registry())
        snap=g.snapshot();snap['state']['entities'][str(eid)]['aura_keywords']=[]
        with self.assertRaises(SnapshotError): Game.from_snapshot(self.rehash(snap),registry())

    def test_captured_context_uses_its_own_native_declaration(self):
        g=self.game();codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        ctx=RuleContext(g.state,self.source(g),1);encoded=codec.encode(ctx)
        self.assertEqual(codec.decode(encoded).state.entities[self.recipient(g)].aura_keywords,{Keyword.CHARGE})
        state=deepcopy(g.state);src=state.entities[self.source(g)]
        src.abilities=[replace(a,keyword_aura=replace(AURA,tribes_any=())) if a.kind=='keyword_aura' else a for a in src.abilities]
        with self.assertRaises(ValueError): codec.decode(codec.encode(replace(ctx,state=state)))

    def test_schema_protocol_rejects_old_missing_or_nonstrict_versions(self):
        g=self.game();snap=g.snapshot();self.assertEqual(snap['schema_version'],266)
        self.assertEqual(snap['ruleset']['id'],'prototype-v302');self.assertEqual(snap['mechanics_version']['version'],CORE_EFFECTS_VERSION)
        for value in (*range(1,218),True,185.0,217):
            bad=deepcopy(snap);bad['schema_version']=value
            with self.subTest(value=value),self.assertRaises(SnapshotError): Game.from_snapshot(bad,registry())


if __name__=='__main__': unittest.main()
