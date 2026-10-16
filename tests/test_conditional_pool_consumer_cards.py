"""Starting facts and current physical conditions feed ordinary shared generation."""
from dataclasses import replace
import json,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.conditional_pool_consumer_cards import OFFICER,HISTORIAN,GORILLA,ROOTS,IDENTITIES,POOL_ID,load_batch
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,DeckPolicy,DeckSpec,Game,
    MatchSetup,PlayCard,PlayerSetup,Scenario,SelectChoice,TargetSpec,Zone)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.deck_conditions import UnknownDeckFacts
from hs_sim.engine.effects import AddToHand,ChangeManaCrystals,ChoiceOption,Destroy,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec,OpeningHook,Rarity,TribeChangeSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference,DestroyDeckMatching
from hs_sim.targets import canonical_digest

P='k111.test.';YETI='CORE_CS2_182';ALL='DINO_435';DRAGON='CORE_EX1_043';SPELL='CS2_032';ORIGINAL_SPELL='CORE_EX1_238';UNKNOWN=P+'unknown'
CTX=GenerationContext('k111-explicit-experiment','experimental');MEMBERS=(GORILLA,ALL,DRAGON,SPELL)
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=(),factions=(),subtypes=())


def registry(members=MEMBERS,mode=None,pool=True,opening=None):
    r=build_registry()
    if UNKNOWN in members:r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,3,
        CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=('mech','dragon'),factions=(),subtypes=())))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'k111-explicit-v1',CTX.target_id,CTX.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    r.register_behavior(P+'fail',lambda c:(_ for _ in()).throw(ResolutionError('K111 deliberate delivery failure')))
    def change(c):return(ChangeMinionTribes(CardReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',('dragon',)),c.source_id),)
    r.register_behavior(P+'dragon',change);r.register_card(CardDefinition(P+'dragon','Change current tribe',CardType.SPELL,on_play=P+'dragon',metadata=META,
        targeting=TargetSpec(zones=(Zone.HAND,Zone.BOARD),kinds=(CardType.MINION,))))
    r.register_behavior(P+'summonless',lambda c:())
    def prepare(c):
        effects=[ChangeManaCrystals(c.player_id,9,filled=True),AddToHand(c.player_id,OFFICER,c.source_id)]
        if opening=='remove':effects.append(DestroyDeckMatching(c.player_id,PoolQuery(kinds=(CardType.SPELL,)),99,'first',c.source_id))
        if opening=='generated':effects.append(AddToHand(c.player_id,ORIGINAL_SPELL,c.source_id))
        return tuple(effects)
    r.register_behavior(P+'opening',prepare)
    r.register_card(CardDefinition(P+'opening','Opening fixture',CardType.MINION,cost=1,attack=1,health=1,
        metadata=replace(META,collectible=True,rarity=Rarity.COMMON),opening_hooks=(OpeningHook('before_deal',P+'opening'),)))
    if mode:
        def eligible(c):return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id in ROOTS
        def watch(c):
            if mode=='fail':return(InvokeBehavior(P+'fail',c.source_id,1),)
            tail=(Destroy(c.event.source_id,c.source_id),)if mode=='retire'else()
            return(RequestChoice(1,(ChoiceOption('ok','Continue',tail),ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),)
        r.register_trigger_condition(P+'eligible',eligible);r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(P+'watch','Delivery reaction',CardType.MINION,health=8,metadata=META,
            limited_triggers=(LimitedTriggerSpec('card_created',P+'watch',condition_id=P+'eligible'),)))
    r.validate();return r


class ConditionalPoolConsumerTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),members=MEMBERS,mode=None,pool=True,context=CTX):
        self.config=(members,mode,pool,None)
        if mode:board=(*board,P+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8)),seed=111,generation_context=context),registry(*self.config))
    def opening(self,spell=False,mode=None,pool=True):
        self.config=(MEMBERS,None,pool,mode);r=registry(*self.config)
        cards=(P+'opening',OFFICER,ORIGINAL_SPELL if spell else YETI,*(YETI,)*5)
        policy=DeckPolicy('k111-explicit-opening',CTX.target_id,'experimental',(P+'opening',OFFICER,ORIGINAL_SPELL,YETI),deck_size=8,max_copies=8)
        setup=MatchSetup((DeckSpec('HERO_02','HERO_02bp',CardClass.SHAMAN,cards),
            DeckSpec('HERO_08','HERO_08bp',CardClass.MAGE,(YETI,)*8)),policy,'GAME_005',111,1)
        g=Game.from_decks(setup,r)
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        return g
    def play(self,g,cid,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target,len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def pick(self,g,cid=None):
        q=g.state.pending_choice;option=next(o for o in q.options if cid is None or o.card_id==cid)
        g.apply(SelectChoice(q.player_id,q.id,(option.id,)))
    def created(self,g,source):return[g.state.entities[e.target_id]for e in g.events if e.kind=='card_created'and e.source_id==source]
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry(*self.config))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())
            for field in('resolution_frame','rng_state','pool_id','DiscoveryPick'):self.assertNotIn('"'+field+'"',public)
        return other

    def test_complete_five_raw_rows_six_faces_and_current_stats_tribes_identities(self):
        d=load_batch();r=registry();self.assertEqual(len(d['cards']+d['evidence_only']),5);self.assertEqual(len(d['official_observations']['observations']),6)
        norm=lambda x:re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',x)
        for row in d['cards']+d['evidence_only']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        for row in d['cards']:
            raw=row['record'];card=r.card(raw['id']);self.assertEqual(card.metadata,replace(metadata_from_record(raw),deck_identity=IDENTITIES[card.id]));self.assertEqual((card.cost,card.attack,card.health),(raw['cost'],raw['attack'],raw['health']))
            for o in(o for o in d['official_observations']['observations']if o['card_id']==card.id):
                face=o['face'];en=o['locale']=='en_US';self.assertEqual(face['name'],raw['name_en'if en else'name']);self.assertEqual(norm(face['text']),norm(raw['text_en'if en else'text']))
        self.assertEqual(r.card(GORILLA).metadata.tribes,('mech','beast'));self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])

    def test_officer_unknown_starting_facts_fail_with_no_rng_or_paid_state(self):
        g=self.game((OFFICER,));saved=g.snapshot()
        with self.assertRaisesRegex((UnknownDeckFacts,ResolutionError),'Starting deck facts'):self.play(g,OFFICER)
        self.assertEqual(g.snapshot(),saved)

    def test_officer_real_no_spell_opening_gets_any_class_seven_cost_spell_for_two(self):
        g=self.opening();source=self.play(g,OFFICER);new,=self.created(g,source)
        self.assertEqual(new.card_id,SPELL);self.assertEqual(quote_cost(g.state,g.registry,new).amount,2)
        self.assertEqual(g.registry.card(new.card_id).cost,7);self.assertTrue(g.state.opening is not None);self.portable(g)

    def test_officer_starting_spell_still_generates_without_discount(self):
        g=self.opening(spell=True);source=self.play(g,OFFICER);new,=self.created(g,source)
        self.assertEqual(new.card_id,SPELL);self.assertEqual(quote_cost(g.state,g.registry,new).amount,7);self.portable(g)

    def test_officer_destroyed_starting_spell_does_not_change_original_false_condition(self):
        g=self.opening(spell=True,mode='remove')
        self.assertFalse(any(g.registry.card(g.state.entities[i].card_id).kind==CardType.SPELL for i in g.state.players[1].deck))
        source=self.play(g,OFFICER);new,=self.created(g,source);self.assertEqual(quote_cost(g.state,g.registry,new).amount,7);self.portable(g)

    def test_officer_generated_hand_spell_does_not_change_original_true_condition(self):
        g=self.opening(mode='generated');self.assertTrue(any(g.state.entities[i].card_id==ORIGINAL_SPELL for i in g.state.players[1].hand))
        source=self.play(g,OFFICER);new,=self.created(g,source);self.assertEqual(quote_cost(g.state,g.registry,new).amount,2);self.portable(g)

    def test_officer_without_explicit_pool_rolls_back_actual_paid_action(self):
        g=self.opening(pool=False);saved=g.snapshot()
        with self.assertRaises((ResolutionError,ValueError)):self.play(g,OFFICER)
        self.assertEqual(g.snapshot(),saved)

    def test_historian_without_held_dragon_needs_no_pool_or_generation_context(self):
        g=self.game((HISTORIAN,YETI),pool=False,context=None);self.play(g,HISTORIAN)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)

    def test_historian_current_all_tribe_hand_unlocks_ordinary_dragon_discovery(self):
        g=self.game((HISTORIAN,ALL));source=self.play(g,HISTORIAN)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},{ALL,DRAGON});other=self.portable(g)
        for game in(g,other):self.pick(game,DRAGON)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.created(g,source)[0].card_id,DRAGON);self.portable(g)

    def test_historian_reads_current_granted_tribe_in_hand(self):
        g=self.game((P+'dragon',HISTORIAN,YETI));target=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==YETI)
        self.play(g,P+'dragon',target);self.play(g,HISTORIAN);self.assertIsNotNone(g.state.pending_choice);self.pick(g,DRAGON);self.portable(g)

    def test_gorilla_does_not_count_its_own_body_or_enemy_mech(self):
        for enemy in((),(GORILLA,)):
            with self.subTest(enemy=enemy):
                g=self.game((GORILLA,),enemy=enemy,pool=False,context=None);source=self.play(g,GORILLA)
                self.assertIsNone(g.state.pending_choice);self.assertFalse(self.created(g,source));self.portable(g)

    def test_gorilla_other_copy_unlocks_discover_but_source_card_family_is_excluded(self):
        for other_mech in(GORILLA,ALL):
            with self.subTest(other=other_mech):
                g=self.game((GORILLA,),board=(other_mech,));source=self.play(g,GORILLA)
                self.assertEqual([o.card_id for o in g.state.pending_choice.options],[ALL]);self.pick(g,ALL)
                self.assertEqual(self.created(g,source)[0].card_id,ALL);self.portable(g)

    def test_delivery_wait_restores_after_source_dies_and_bad_choice_rolls_back(self):
        g=self.game((GORILLA,),board=(ALL,),mode='retire');source=self.play(g,GORILLA);self.pick(g,ALL)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=g.snapshot()
        q=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,q.id,('bad',)))
        self.assertEqual(g.snapshot(),saved)
        for game in(g,other):game.apply(SelectChoice(1,game.state.pending_choice.id,('ok',)))
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.portable(g)

    def test_unknown_eligible_dragon_or_mech_fails_before_rng_with_no_fallback(self):
        for cid,hand,board in((HISTORIAN,(HISTORIAN,ALL),()),(GORILLA,(GORILLA,),(ALL,))):
            with self.subTest(cid=cid):
                g=self.game(hand,board,members=(ALL,UNKNOWN));saved=g.snapshot()
                with patch('random.Random.randrange',side_effect=AssertionError('RNG before validation'))as rng:
                    with self.assertRaises((ResolutionError,ValueError)):self.play(g,cid)
                    rng.assert_not_called()
                self.assertEqual(g.snapshot(),saved)

    def test_late_delivery_failure_keeps_original_offer_and_rng(self):
        g=self.game((GORILLA,),board=(ALL,),mode='fail');self.play(g,GORILLA);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.pick(g,ALL)
        self.assertEqual(g.snapshot(),saved)


if __name__=='__main__':unittest.main()
