"""Ritual retains its actual discovered card and summons an independent2/3 copy."""
from dataclasses import replace
import json,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.discovered_minion_copy_cards import RITUAL,POOL_ID,BODY,load_batch
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,SpellSchool
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.discovery import DeliverAndSummonDiscoveredMinion
from hs_sim.engine.effects import AddToHand,ChoiceOption,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import ChoiceResult,LimitedTriggerSpec,Rarity,SummonQuantitySpec,SummonStats,Zone
from hs_sim.engine.pools import DiscoverFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

P='k113.test.';MINION='CORE_EX1_007';BATTLECRY='CORE_LOE_039';YETI='CORE_CS2_182';FOREIGN=P+'foreign';UNKNOWN=P+'unknown'
CTX=GenerationContext('k113-explicit-experiment','experimental');MEMBERS=(MINION,BATTLECRY,YETI,RITUAL,FOREIGN)
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=(),factions=(),subtypes=())

def registry(members=MEMBERS,mode=None,pool=True):
    r=build_registry()
    for cid,cls in((FOREIGN,CardClass.MAGE),(UNKNOWN,CardClass.PRIEST)):
        if cid in members:r.register_pool_card(PoolCard(cid,CardType.MINION,3,CardMetadata(True,(cls,),Rarity.COMMON,tribes=(),factions=(),subtypes=())))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'k113-explicit-v1',CTX.target_id,CTX.mode,tuple(PoolMember(c)for c in members),complete=True))
    r.register_card(CardDefinition(P+'double','Spell summon quantity fixture',CardType.MINION,health=5,metadata=META,summon_quantities=(SummonQuantitySpec(2,(CardType.SPELL,)),)))
    r.register_behavior(P+'auto',lambda c:(CastSpell(1,RITUAL,c.source_id,choices='random'),))
    r.register_card(CardDefinition(P+'auto','Auto cast fixture',CardType.SPELL,on_play=P+'auto',metadata=META))
    r.register_behavior(P+'fail',lambda c:(_ for _ in()).throw(ResolutionError('K113 deliberate acquisition failure')))
    if mode:
        def eligible(c):return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==RITUAL
        def watch(c):
            if mode=='fill':return(AddToHand(1,YETI,c.source_id),)
            if mode=='buff':return(BuffStoredCard(CardReference.capture(c.state.entities[c.event.target_id]),attack=5,health=5,source_id=c.source_id),)
            if mode=='fail':return(InvokeBehavior(P+'fail',c.source_id,1),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(P+'watch',watch);r.register_trigger_condition(P+'eligible',eligible)
        r.register_card(CardDefinition(P+'watch','Actual acquisition reaction',CardType.MINION,health=5,metadata=META,
            limited_triggers=(LimitedTriggerSpec('choice_selected'if mode=='fill'else'card_created',P+'watch',condition_id=P+'eligible'),)))
    r.validate();return r

class DiscoveredMinionCopyTests(unittest.TestCase):
    def game(self,hand=(RITUAL,),board=(),members=MEMBERS,mode=None,pool=True,context=CTX):
        self.config=(members,mode,pool)
        if mode:board=(*board,P+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_09',hand=hand,board=board,deck=(YETI,)*8,mana=20,max_mana=20,mana_cap=20),
            PlayerSetup('HERO_08',deck=(YETI,)*8)),seed=113,generation_context=context),registry(*self.config))
    def play(self,g,cid=RITUAL):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid);g.apply(PlayCard(1,eid));return eid
    def pick(self,g,cid=MINION):
        q=g.state.pending_choice;o=next(x for x in q.options if x.card_id==cid);g.apply(SelectChoice(1,q.id,(o.id,)))
    def cards(self,g,zone,cid=MINION):return[g.state.entities[i]for i in getattr(g.state.players[1],zone)if g.state.entities[i].card_id==cid]
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(*self.config));self.assertEqual(other.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for field in('summon_copy_stats','DeliverAndSummonDiscoveredMinion','resolution_frame','rng_state','CopyEntryMaterial'):
                self.assertNotIn('"'+field+'"',public)
        return other

    def test_full_two_raw_rows_two_primary_faces_and_native_metadata(self):
        d=load_batch();r=registry();raw=d['cards'][0]['record'];c=r.card(RITUAL)
        self.assertEqual((c.cost,c.spell_school,c.on_play),(2,SpellSchool.HOLY,BODY));self.assertEqual(c.metadata,metadata_from_record(raw));self.assertEqual(c.metadata.classes,(CardClass.PRIEST,))
        self.assertEqual(len(d['cards']+d['evidence_only']),2);self.assertEqual(len(d['official_observations']['observations']),2)
        for row in d['cards']+d['evidence_only']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        norm=lambda x:re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',x)
        for o in d['official_observations']['observations']:
            face=o['face'];en=o['locale']=='en_US';self.assertEqual(face['name'],raw['name_en'if en else'name']);self.assertEqual(norm(face['text']),norm(raw['text_en'if en else'text']))
        self.assertNotIn('DINO_426e',r.cards);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])

    def test_native_discovery_keeps_printed_hand_card_and_summons_independent_two_three(self):
        g=self.game();source=self.play(g);self.assertEqual({o.card_id for o in g.state.pending_choice.options},{MINION,BATTLECRY});self.pick(g)
        hand,=self.cards(g,'hand');body,=self.cards(g,'board');self.assertEqual((hand.attack,hand.max_health),(1,4));self.assertEqual((body.attack,body.max_health),(2,3));self.assertNotEqual(hand.id,body.id)
        self.assertEqual(g.state.players[1].mana,18);child,=g.state.card_summon_history;self.assertEqual(child.request.cause.source.entity_id,source);self.assertEqual(child.request.materials[0].origin.entity_id,hand.id);self.portable(g)

    def test_offer_and_complete_selection_restore_without_resampling_or_extra_payment(self):
        g=self.game();self.play(g);other=self.portable(g);rng=g._rng.getstate()
        for game in(g,other):self.pick(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g._rng.getstate(),rng);self.portable(g)

    def test_summoned_copy_does_not_execute_its_battlecry(self):
        g=self.game(members=(BATTLECRY,));self.play(g);self.pick(g,BATTLECRY)
        self.assertEqual(len(self.cards(g,'hand',BATTLECRY)),1);self.assertEqual(len(self.cards(g,'board',BATTLECRY)),1);self.assertFalse(g.state.battlecry_history);self.portable(g)

    def test_existing_same_face_hand_is_not_consumed_or_set_to_two_three(self):
        g=self.game(hand=(RITUAL,MINION));old=self.cards(g,'hand')[0].id;self.play(g);self.pick(g)
        self.assertEqual(len(self.cards(g,'hand')),2);self.assertEqual((g.state.entities[old].attack,g.state.entities[old].max_health),(1,4));self.assertEqual(len(self.cards(g,'board')),1);self.portable(g)

    def test_quantity_duplicates_selected_copy_but_keeps_one_original_hand_card(self):
        g=self.game(board=(P+'double',));self.play(g);self.pick(g)
        self.assertEqual(len(self.cards(g,'hand')),1);self.assertEqual([(e.attack,e.max_health)for e in self.cards(g,'board')],[(2,3),(2,3)]);self.assertEqual(g.state.card_summon_history[0].plan.total,2);self.portable(g)

    def test_full_board_still_delivers_hand_card_and_records_failed_copy(self):
        g=self.game(board=(YETI,)*7);self.play(g);self.pick(g);self.assertEqual(len(self.cards(g,'hand')),1);self.assertFalse(self.cards(g,'board'));self.assertEqual(g.state.card_summon_history[0].status,'skipped');self.portable(g)

    def test_full_hand_burns_discovered_card_but_summons_selected_copy(self):
        g=self.game(hand=(RITUAL,)+(YETI,)*9,mode='fill');self.play(g);self.pick(g)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertFalse(self.cards(g,'hand'));body,=self.cards(g,'board');self.assertEqual((body.attack,body.max_health),(2,3))
        burn,=[e for e in g.events if e.kind=='card_burned'];self.assertNotEqual(burn.target_id,body.id);self.assertEqual(g.state.entities[burn.target_id].card_id,MINION);self.portable(g)

    def test_creation_material_is_accepted_before_later_acquisition_buff(self):
        g=self.game(mode='buff');self.play(g);self.pick(g);hand,=self.cards(g,'hand');body,=self.cards(g,'board')
        self.assertEqual((hand.attack,hand.max_health),(6,9));self.assertEqual((body.attack,body.max_health),(2,3));self.portable(g)

    def test_acquisition_wait_preserves_created_hand_and_accepted_copy_before_body_delivery(self):
        g=self.game(mode='wait');self.play(g);self.pick(g);self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(self.cards(g,'hand')),1);self.assertFalse(self.cards(g,'board'))
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,g.state.pending_choice.id,('bad',)))
        self.assertEqual(g.snapshot(),saved)
        for game in(g,other):game.apply(SelectChoice(1,game.state.pending_choice.id,('ok',)))
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.cards(g,'board')),1);self.portable(g)

    def test_acquisition_failure_rolls_back_hand_creation_copy_acceptance_and_rng(self):
        g=self.game(mode='fail');self.play(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.pick(g)
        self.assertEqual(g.snapshot(),saved)

    def test_empty_eligible_pool_creates_nothing_and_consumes_no_random(self):
        g=self.game(members=(YETI,));rng=g._rng.getstate();self.play(g);self.assertIsNone(g.state.pending_choice);self.assertEqual(g._rng.getstate(),rng);self.assertFalse(g.state.card_summon_history);self.portable(g)

    def test_missing_context_pool_or_unknown_eligible_card_fails_before_rng(self):
        for pool,context,members in((False,CTX,MEMBERS),(True,None,MEMBERS),(True,CTX,(MINION,UNKNOWN))):
            with self.subTest(pool=pool,context=context):
                g=self.game(pool=pool,context=context,members=members);saved=g.snapshot()
                with patch('random.Random.randrange',side_effect=AssertionError('RNG before complete validation'))as rng:
                    with self.assertRaises((ValueError,ResolutionError)):self.play(g)
                    rng.assert_not_called()
                self.assertEqual(g.snapshot(),saved)

    def test_real_automatic_spell_retains_hand_and_summons_copy_without_paying_generated_spell(self):
        g=self.game(hand=(P+'auto',),members=(MINION,));self.play(g,P+'auto');self.assertIsNone(g.state.pending_choice);self.assertEqual(len(self.cards(g,'hand')),1);self.assertEqual(len(self.cards(g,'board')),1);self.assertEqual(g.state.players[1].mana,20);self.portable(g)

    def test_outcome_codec_rejects_changed_actual_choice_actor_and_context(self):
        g=self.game();self.play(g);q=g.state.pending_choice;option=q.options[0];branch=g._frame.options[0].effects[0]
        selected=replace(branch,choice_result=ChoiceResult(q,(option.id,)));effect=DeliverAndSummonDiscoveredMinion(selected,CTX);codec=FrameCodec(g.mechanics,g.registry);self.assertEqual(codec.decode(codec.encode(effect)),effect)
        bad=replace(effect,discovery=replace(selected,choice_result=ChoiceResult(replace(q,player_id=2),(option.id,))))
        with self.assertRaises((ValueError,SnapshotError)):codec.decode(codec.encode(bad))

    def test_finite_stats_declaration_preserves_ordinary_discovery_and_rejects_invalid_shapes(self):
        g=self.game();self.play(g);spec=g._frame.options[0].effects[0].batch.spec
        for changes in(dict(summon_copy_stats=(2,3)),dict(summon_copy_stats=SummonStats(attack=2)),dict(destination='board'),dict(cause=None),dict(discoveries=2),dict(delivery='after_all'),dict(freeze_summoned=True),dict(heal_hero_by_printed_cost=True)):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):replace(spec,**changes)
        self.assertIsNone(DiscoverFromPool(1,POOL_ID).summon_copy_stats)

if __name__=='__main__':unittest.main()
