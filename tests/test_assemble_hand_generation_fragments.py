"""Native filtered generation and discoveries use the actual new carrier/player."""
from dataclasses import asdict,replace
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.assemble_hand_generation_fragments import SOURCES,CHILD,load_batch,register_assemble_hand_generation_fragments
from hs_sim.cards.native_assemble_entry_cards import NURTURER,FLESH,POOL_ID as ASSEMBLY_POOL
from hs_sim.engine import CardDefinition,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,Zone
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.effects import AddToHand,ChangeControl,ChoiceOption,Damage,GainArmor,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass,CardMetadata,DamageKind,LimitedTriggerSpec,Rarity,SpellSchool,TargetSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import TargetValidationError,canonical_digest
from tools.card_batch import check_face,sha
from test_assemble_draw_armor_heal_fragments import fixture as base_fixture,META,DECK,COIN,KILL

WHELP,RAIDER,MACAW,BOOK,PIRATE,DISCOVER,NETHER,VICAR,PEDDLER,COIN_BODY=SOURCES
FLY,LOOT,RUST,DOOM,HEAL='CORE_UNG_809','CORE_EX1_096','CORE_SW_072','CORE_NEW1_021','EDR_971'
P='fixture.assemble_hand_generation.'
D1,D5,BEAST,SEA,N1,N2,N3,WD,MA,ROG,LOCK=(P+x for x in
    ('dragon1','dragon5','beast','pirate','demon1','demon2','demon3','warlock_demon','mage_arcane','rogue_spell','warlock_spell'))
PAL=tuple(P+'holy_paladin'+str(i)for i in (1,2,3));MAG=tuple(P+'holy_mage'+str(i)for i in (1,2,3))
GENERAL=(D1,D5,BEAST,SEA,N1,N2,N3,WD,MA,ROG,LOCK)+PAL+MAG
NOOP,WATCH,FILL,FAULT,GIVE,UNKNOWN,HURT=(P+x for x in ('noop','watch','fill','fault','give','unknown','hurt'))
CTX=GenerationContext('k406-reviewed-hand-generation-fixture','experimental')
POOL='constructed.cards'
HERO={CardClass.WARRIOR:'HERO_01',CardClass.HUNTER:'HERO_05',CardClass.ROGUE:'HERO_03',
    CardClass.MAGE:'HERO_08',CardClass.DEMON_HUNTER:'HERO_10',CardClass.PALADIN:'HERO_04',CardClass.WARLOCK:'HERO_07'}


def gen_meta(cls=CardClass.NEUTRAL,tribes=()):
    return CardMetadata(True,(cls,),Rarity.COMMON,tribes=tribes,factions=(),subtypes=())


@lru_cache(maxsize=None)
def fixture(mode='normal',role='writer'):
    r=base_fixture.__wrapped__('no_pool');r._version+='.k406.'+mode;r.register_behavior(NOOP,lambda c:())
    for cid,cost,tribe,cls in ((D1,1,'dragon',CardClass.NEUTRAL),(D5,5,'dragon',CardClass.NEUTRAL),
            (BEAST,1,'beast',CardClass.NEUTRAL),(SEA,1,'pirate',CardClass.NEUTRAL),
            (N1,1,'demon',CardClass.NEUTRAL),(N2,2,'demon',CardClass.NEUTRAL),(N3,3,'demon',CardClass.NEUTRAL),
            (WD,2,'demon',CardClass.WARLOCK)):
        d=CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=1,health=4,metadata=gen_meta(cls,(tribe,)))
        r.register_card(d);r.register_pool_card(PoolCard.from_definition(d))
    for cid,cost,cls,school in (*((cid,i,CardClass.PALADIN,SpellSchool.HOLY)for i,cid in enumerate(PAL,1)),
            *((cid,i,CardClass.MAGE,SpellSchool.HOLY)for i,cid in enumerate(MAG,1)),
            (MA,4,CardClass.MAGE,SpellSchool.ARCANE),(ROG,1,CardClass.ROGUE,SpellSchool.SHADOW),
            (LOCK,1,CardClass.WARLOCK,SpellSchool.FEL)):
        d=CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=NOOP,spell_school=school,metadata=gen_meta(cls))
        r.register_card(d);r.register_pool_card(PoolCard.from_definition(d))
    if mode=='unknown':r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,1,gen_meta(tribes=('pirate',))))
    members=(RAIDER,)if mode=='donor'else (UNKNOWN,)if mode=='unknown'else GENERAL
    if mode!='no_general':r.register_pool(PoolDefinition(POOL,'complete-diagnostic-hand-domain-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(x)for x in members),complete=True))
    assembly=(LOOT,BOOK,RUST)if mode=='flesh'else(FLY,VICAR,LOOT)
    if mode=='missing':r._assemble_templates.pop(VICAR)
    if mode!='no_assembly':r.register_pool(PoolDefinition(ASSEMBLY_POOL,'three-real-hand-text-sources-v1',CTX.target_id,
        CTX.mode,tuple(PoolMember(x)for x in assembly),complete=True))
    def fault(c):raise ResolutionError('deliberate assembled hand-generation fault')
    r.register_behavior(FAULT,fault)
    def eligible(c):return c.event.player_id==c.player_id and c.state.entities[c.event.target_id].card_id in GENERAL
    r.register_trigger_condition(WATCH,eligible)
    r.register_behavior(WATCH,lambda c:(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),
        ChoiceOption('fault','Fail',(GainArmor(c.player_id,1),InvokeBehavior(FAULT,c.source_id,c.player_id)))),c.source_id),))
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,
        limited_triggers=(LimitedTriggerSpec('card_created',WATCH,condition_id=WATCH),)))
    r.register_trigger_condition(FILL,lambda c:c.state.entities[c.event.target_id].card_id.startswith('assemble:'))
    r.register_behavior(FILL,lambda c:(AddToHand(c.player_id,COIN,c.source_id),))
    r.register_card(CardDefinition(FILL,FILL,CardType.MINION,health=20,metadata=META,
        limited_triggers=(LimitedTriggerSpec('minion_summoned',FILL,condition_id=FILL),)))
    r.register_behavior(GIVE,lambda c:(ChangeControl(c.target_id,2),))
    r.register_card(CardDefinition(GIVE,GIVE,CardType.SPELL,on_play=GIVE,metadata=META,
        targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly')))
    r.register_behavior(HURT,lambda c:tuple(Damage(c.state.players[p].hero_id,12,c.source_id,DamageKind.EFFECT)for p in(1,2)))
    r.register_card(CardDefinition(HURT,HURT,CardType.SPELL,on_play=HURT,metadata=META))
    return r


class AssembleHandGenerationTests(unittest.TestCase):
    def game(self,hand=(),board=(),mode='normal',hero='HERO_08'):
        self.mode=mode
        return Game.from_scenario(Scenario((
            PlayerSetup(hero,hand=hand,board=board,deck=DECK,mana=30,max_mana=30,mana_cap=30),
            PlayerSetup('HERO_08',deck=(COIN,)*12,mana=30,max_mana=30,mana_cap=30)),seed=406,generation_context=CTX),fixture(mode))
    def play(self,g,cid,target=None):
        pid=g.state.active_player;eid=next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(pid,eid,target_id=target));return eid
    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def choose_face(self,g,cid):self.choose(g,next(x.id for x in g.state.pending_choice.options if x.card_id==cid))
    def added(self,g,before=(),pid=1):return [g.state.entities[i]for i in g.state.players[pid].hand if i not in before]
    def generated(self,g):return [e for e in g.state.entities.values()if e.card_id in GENERAL]
    def portable(self,g):
        reader=fixture(self.mode,'reader');self.assertIsNot(reader,g.registry);saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved,reader).snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);return saved

    def valid(self,g,source,cid):
        d=g.registry.card(cid);classes=d.metadata.classes
        if source==WHELP:return d.kind==CardType.MINION and 'dragon'in d.metadata.tribes and d.cost<=3
        if source==RAIDER:return d.kind==CardType.MINION and 'pirate'in d.metadata.tribes
        if source==MACAW:return d.kind==CardType.MINION and 'beast'in d.metadata.tribes
        if source==BOOK:return d.kind==CardType.SPELL and CardClass.MAGE in classes
        if source==PIRATE:return CardClass.ROGUE not in classes and CardClass.NEUTRAL not in classes
        if source==DISCOVER:return d.kind==CardType.SPELL and d.cost==1
        if source==NETHER:return d.kind==CardType.MINION and 'demon'in d.metadata.tribes and (CardClass.NEUTRAL in classes or CardClass.DEMON_HUNTER in classes)
        if source==VICAR:return d.kind==CardType.SPELL and d.spell_school==SpellSchool.HOLY and CardClass.PALADIN in classes
        if source==PEDDLER:return d.cost==1 and (CardClass.WARLOCK in classes or CardClass.NEUTRAL in classes)
        return cid==COIN

    def test_eleven_complete_records_twenty_two_primary_faces_and_explicit_coin_zero(self):
        data=load_batch();rows={x['record']['id']:x for x in data['existing_dependencies']};r=build_registry()
        self.assertEqual(tuple(rows),SOURCES+(CHILD,));self.assertEqual(len(data['official_observations']),22)
        self.assertIsNone(rows[COIN]['record']['cost']);self.assertNotIn('COST',rows[COIN]['record']['tags'])
        self.assertEqual(data['numeric_normalizations'],{COIN:{'cost':0}});self.assertEqual(r.card(COIN).cost,0)
        for obs in data['official_observations']:
            row=rows[obs['card_id']];check_face(row['record'],obs['face'],obs['locale'],numeric_normalizations=data['numeric_normalizations'].get(obs['card_id']))
            path=Path(obs['response_file']);self.assertEqual(sha(path),obs['response_sha256'])
            self.assertEqual([x for x in json.loads(path.read_text('utf-8-sig'))['cards']if x['id']==row['record']['dbf_id']],[obs['face']])
        for cid,row in rows.items():self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])

    def test_all_ten_whole_definitions_reconstruct_without_new_callback_or_query_mutation(self):
        r=build_registry();fp=r.fingerprint();count=len(r.cards)
        for cid in SOURCES:
            t=r.assemble_templates[cid];d=r.card(cid);face=r.card(AssembleRecipe(cid,cid,'top').card_id)
            self.assertEqual(asdict(face),asdict(d)|{'id':face.id});self.assertEqual(t.suffix.behavior_id,d.battlecry or d.deathrattle)
        self.assertEqual((r.fingerprint(),len(r.cards)),(fp,count))
        with self.assertRaises(UnsupportedDefinitionError):r.pool(ASSEMBLY_POOL,CTX)

    def test_each_paid_battlecry_uses_exact_original_filters_and_count(self):
        for source in SOURCES:
            with self.subTest(source=source):
                cid=AssembleRecipe(FLY,source,'bottom').card_id;r=fixture();cls=r.card(source).metadata.classes[0]
                g=self.game(hand=(cid,),hero=HERO.get(cls,'HERO_08'));before=tuple(g.state.players[1].hand);mana=g.state.players[1].mana
                eid=self.play(g,cid)
                if g.state.pending_choice:
                    options=g.state.pending_choice.options;self.assertEqual(len(options),3)
                    self.assertTrue(all(self.valid(g,source,x.card_id)for x in options));self.choose(g,options[0].id)
                added=self.added(g,before);self.assertEqual(len(added),2 if source==BOOK else 1)
                self.assertTrue(all(self.valid(g,source,x.card_id)for x in added));self.assertEqual(g.state.players[1].mana,mana-1)
                self.assertEqual(g.state.battlecry_history[-1].source_id,eid);self.assertTrue(g.state.battlecry_history[-1].completed)

    def test_real_nurturer_discovery_waiting_restores_replays_and_failed_delivery_rolls_back(self):
        cid=AssembleRecipe(FLY,VICAR,'bottom').card_id
        g=self.game(hand=(NURTURER,),board=(WATCH,),hero='HERO_04');self.play(g,NURTURER);self.choose_face(g,cid)
        eid=self.play(g,cid);self.assertEqual({x.card_id for x in g.state.pending_choice.options},set(PAL));self.portable(g)
        selected=g.state.pending_choice.options[0].id;self.choose(g,selected);saved=self.portable(g)
        with self.assertRaisesRegex(ResolutionError,'assembled hand-generation fault'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'ok');self.assertTrue(g.state.battlecry_history[-1].completed)
        self.assertEqual(g.state.battlecry_history[-1].source_id,eid);self.assertEqual(len(self.generated(g)),1)
        enemy=json.dumps(g.observe(2),ensure_ascii=False)
        for private in ('rng_before','candidate_card_ids','resolution_frame','generation_policy'):self.assertNotIn(private,enemy)

    def test_real_flesh_death_body_generates_two_mage_spells_not_old_draw_or_battlecry(self):
        cid=AssembleRecipe(LOOT,BOOK,'bottom').card_id
        g=self.game(hand=(FLESH,KILL),mode='flesh');self.play(g,FLESH);self.choose_face(g,cid);eid=self.play(g,cid)
        self.assertFalse(self.generated(g));before=tuple(g.state.players[1].hand);self.play(g,KILL,eid)
        cards=self.added(g,before);self.assertEqual(len(cards),2);self.assertTrue(all(self.valid(g,BOOK,x.card_id)for x in cards))
        self.assertEqual(len({x.id for x in cards}),2);self.assertFalse(g.state.draw_history);self.assertTrue(g.state.deathrattle_history[-1].completed)

    def test_owner_end_generation_does_not_fire_at_battlecry_or_heal_old_heroes(self):
        cid=AssembleRecipe(HEAL,WHELP,'bottom').card_id
        g=self.game(hand=(cid,HURT));self.play(g,HURT);eid=self.play(g,cid);self.assertFalse(self.generated(g));g.apply(EndTurn(1))
        self.assertEqual([x.card_id for x in self.generated(g)],[D1]);self.assertEqual(len(g.state.end_turn_history),1)
        self.assertEqual(g.state.end_turn_history[0].capture.subject.source_id,eid)
        self.assertEqual([g.state.entities[g.state.players[p].hero_id].health for p in(1,2)],[18,18])

    def test_owner_start_two_card_generation_keeps_original_count_and_window(self):
        cid=AssembleRecipe(DOOM,BOOK,'bottom').card_id
        g=self.game(hand=(cid,));self.play(g,cid);g.apply(EndTurn(1));self.assertFalse(self.generated(g));g.apply(EndTurn(2))
        cards=self.generated(g);self.assertEqual(len(cards),2);self.assertTrue(all(self.valid(g,BOOK,x.card_id)for x in cards))

    def test_transfer_changes_current_discovery_player_and_class_not_the_old_supplier(self):
        cid=AssembleRecipe(DOOM,VICAR,'bottom').card_id
        g=self.game(hand=(cid,GIVE),hero='HERO_04');eid=self.play(g,cid);self.play(g,GIVE,eid);g.apply(EndTurn(1))
        q=g.state.pending_choice;self.assertEqual(q.player_id,2);self.assertEqual({x.card_id for x in q.options},set(MAG))
        self.choose(g,q.options[0].id);self.assertEqual(len([e for e in self.added(g,pid=2)if e.card_id in MAG]),1)

    def test_fixed_coin_uses_dead_source_end_and_new_controller_without_random_pool(self):
        dead=AssembleRecipe(LOOT,COIN_BODY,'bottom').card_id
        g=self.game(hand=(KILL,),board=(dead,),mode='no_general');eid=g.state.players[1].board[0];self.play(g,KILL,eid)
        self.assertEqual([x.card_id for x in self.added(g)],[COIN]);self.assertFalse(g.state.draw_history)
        end=AssembleRecipe(HEAL,COIN_BODY,'bottom').card_id
        g=self.game(hand=(end,GIVE),hero='HERO_03',mode='no_general');eid=self.play(g,end);self.play(g,GIVE,eid)
        g.apply(EndTurn(1));self.assertFalse(self.added(g));g.apply(EndTurn(2))
        self.assertEqual([x.card_id for x in self.added(g,pid=2)],[COIN,COIN])

    def test_full_hand_two_samples_are_not_pruned_or_refunded(self):
        cid=AssembleRecipe(FLY,BOOK,'bottom').card_id
        empty=self.game(hand=(cid,));self.play(empty,cid);selected=[x.card_id for x in self.generated(empty)]
        full=self.game(hand=(cid,)+(COIN,)*9);before=full.state.players[1].mana;self.play(full,cid)
        self.assertEqual([x.card_id for x in self.generated(full)],selected);self.assertEqual(len(full.state.players[1].hand),10)
        self.assertEqual(full.state.players[1].mana,before-1);self.assertEqual(full.snapshot()['rng_state'],empty.snapshot()['rng_state'])
        self.assertTrue(any(e.kind=='card_burned'for e in full.events))

    def test_discovery_full_hand_keeps_complete_offer_and_burns_selected_card(self):
        cid=AssembleRecipe(FLY,VICAR,'bottom').card_id
        g=self.game(hand=(cid,)+(COIN,)*9,board=(FILL,),hero='HERO_04');self.play(g,cid)
        q=g.state.pending_choice;self.assertEqual(len(q.options),3);self.assertEqual({x.card_id for x in q.options},set(PAL))
        self.assertEqual(len(g.state.players[1].hand),10);self.choose(g,q.options[0].id)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertTrue(any(e.kind=='card_burned'for e in g.events))

    def test_actual_assembled_source_identity_does_not_silently_exclude_the_suffix_donor(self):
        cid=AssembleRecipe(FLY,RAIDER,'bottom').card_id
        g=self.game(hand=(cid,),mode='donor',hero='HERO_01');self.play(g,cid)
        self.assertEqual([x.card_id for x in self.added(g)],[RAIDER])

    def test_missing_generation_domain_and_unknown_eligible_member_rollback_payment_and_rng(self):
        cid=AssembleRecipe(FLY,RAIDER,'bottom').card_id
        for mode in ('no_general','unknown'):
            g=self.game(hand=(cid,),mode=mode,hero='HERO_01');saved=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,cid)
            self.assertEqual(g.snapshot(),saved)

    def test_missing_assembly_domain_fragment_and_full_source_pin_fail_without_partial_installation(self):
        for mode in ('no_assembly','missing'):
            g=self.game(hand=(NURTURER,),mode=mode,hero='HERO_04');saved=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,NURTURER)
            self.assertEqual(g.snapshot(),saved)
        r=build_registry()
        for cid in SOURCES:r._assemble_templates.pop(cid)
        r._cards[COIN]=replace(r.card(COIN),cost=1)
        with self.assertRaisesRegex(TargetValidationError,'complete original source or Coin'):register_assemble_hand_generation_fragments(r)
        self.assertTrue(all(cid not in r.assemble_templates for cid in SOURCES))


if __name__=='__main__':unittest.main()
