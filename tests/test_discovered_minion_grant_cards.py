"""Ordinary Taunt discovery forwards a fixed grant to actual generated material."""
from dataclasses import replace
import json,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.discovered_minion_grant_cards import GUY,POOL_ID,BODY,load_batch
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import AddToHand,ChoiceOption,InvokeBehavior,RequestChoice,Silence
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CostSpec,Keyword,LimitedTriggerSpec,Rarity,SummonStats,TargetSpec,Zone
from hs_sim.engine.pools import DiscoverFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.targets import canonical_digest

P='k114.test.';TAUNT='CORE_CS2_179';DRAGON='CORE_UNG_848';YETI='CORE_CS2_182';FOREIGN=P+'foreign';UNKNOWN=P+'unknown'
CTX=GenerationContext('k114-explicit-experiment','experimental');MEMBERS=(TAUNT,DRAGON,YETI,GUY,FOREIGN)
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=(),factions=(),subtypes=())

def registry(members=MEMBERS,mode=None,pool=True):
    r=build_registry()
    for cid,cls in((FOREIGN,CardClass.MAGE),(UNKNOWN,CardClass.NEUTRAL)):
        if cid in members:r.register_pool_card(PoolCard(cid,CardType.MINION,4,CardMetadata(True,(cls,),Rarity.COMMON,tribes=(),factions=(),subtypes=()),keywords=(Keyword.TAUNT,)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'k114-explicit-v1',CTX.target_id,CTX.mode,tuple(PoolMember(c)for c in members),complete=True))
    for name,body in(('auto',lambda c:(CastSpell(1,GUY,c.source_id,choices='random'),)),('fail',lambda c:(_ for _ in()).throw(ResolutionError('K114 deliberate acquisition failure'))),('silence',lambda c:(Silence(c.target_id),))):
        r.register_behavior(P+name,body)
        r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if name=='silence'else None))
    if mode:
        def eligible(c):return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==GUY
        def watch(c):
            if mode=='fill':return(AddToHand(1,YETI,c.source_id),)
            if mode=='fail':return(InvokeBehavior(P+'fail',c.source_id,1),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(P+'watch',watch);r.register_trigger_condition(P+'eligible',eligible)
        r.register_card(CardDefinition(P+'watch','Actual generation reaction',CardType.MINION,health=5,metadata=META,
            limited_triggers=(LimitedTriggerSpec('choice_selected'if mode=='fill'else'card_created',P+'watch',condition_id=P+'eligible'),)))
    r.validate();return r

class DiscoveredMinionGrantTests(unittest.TestCase):
    def game(self,hand=(GUY,),board=(),members=MEMBERS,mode=None,pool=True,context=CTX):
        self.config=(members,mode,pool)
        if mode:board=(*board,P+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_01',hand=hand,board=board,deck=(YETI,)*8,mana=20,max_mana=20,mana_cap=20),
            PlayerSetup('HERO_08',deck=(YETI,)*8)),seed=114,generation_context=context),registry(*self.config))
    def play(self,g,cid=GUY,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target,len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def pick(self,g,cid=TAUNT):
        q=g.state.pending_choice;o=next(x for x in q.options if x.card_id==cid);g.apply(SelectChoice(1,q.id,(o.id,)))
    def hand(self,g,cid=TAUNT):return[g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==cid]
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(*self.config));self.assertEqual(other.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for field in('minion_grant','resolution_frame','rng_state','CreatedMinionGrant','pool_id'):self.assertNotIn('"'+field+'"',public)
        return other

    def test_full_three_raw_rows_two_primary_faces_native_spell_and_exact_editions(self):
        d=load_batch();r=registry();raw=d['cards'][0]['record'];c=r.card(GUY)
        self.assertEqual((c.cost,c.on_play),(1,BODY));self.assertEqual(c.metadata,replace(metadata_from_record(raw),deck_identity='WON_350'));self.assertFalse(c.keywords)
        self.assertEqual(len(d['cards']+d['evidence_only']),3);self.assertEqual(len(d['official_observations']['observations']),2)
        for row in d['cards']+d['evidence_only']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        norm=lambda x:re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',x)
        for o in d['official_observations']['observations']:
            f=o['face'];en=o['locale']=='en_US';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']))
        self.assertEqual(set(r.generation_family(GUY)),{GUY,'WON_350','CFM_940'});self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])

    def test_paid_native_discovery_only_taunt_minions_and_fixed_permanent_hand_stats(self):
        g=self.game();source=self.play(g);self.assertEqual({o.card_id for o in g.state.pending_choice.options},{TAUNT,DRAGON});self.pick(g)
        card,=self.hand(g);self.assertEqual((card.attack,card.max_health),(4,7));self.assertEqual(card.base_cost,4);self.assertEqual(g.state.players[1].mana,19)
        grant,=[e for e in card.enchantments if e.label=='created_minion_grant'];self.assertEqual((grant.source_id,grant.attack,grant.health,grant.expires_turn),(source,1,2,None));self.assertFalse(g.state.card_summon_history);self.portable(g)

    def test_waiting_offer_restores_and_selection_has_no_new_rng_or_payment(self):
        g=self.game();self.play(g);other=self.portable(g);rng=g._rng.getstate()
        for game in(g,other):self.pick(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.players[1].mana,19);self.portable(g)

    def test_old_same_face_hand_card_is_not_selected_grant_recipient(self):
        g=self.game(hand=(GUY,TAUNT));old=self.hand(g)[0].id;self.play(g);self.pick(g)
        self.assertEqual((g.state.entities[old].attack,g.state.entities[old].max_health),(3,5));new,=[e for e in self.hand(g)if e.id!=old];self.assertEqual((new.attack,new.max_health),(4,7));self.portable(g)

    def test_generated_grant_survives_normal_play_and_silence_uses_common_removal(self):
        g=self.game(hand=(GUY,P+'silence'));self.play(g);self.pick(g);eid=self.play(g,TAUNT)
        self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].max_health),(4,7));self.assertEqual(g.state.players[1].mana,15)
        self.play(g,P+'silence',eid);self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].max_health),(3,5));self.portable(g)

    def test_creation_observer_sees_complete_grant_and_restore_keeps_original_entity(self):
        g=self.game(mode='wait');self.play(g);self.pick(g);self.assertIsNotNone(g.state.pending_choice);card,=self.hand(g);self.assertEqual((card.attack,card.max_health),(4,7))
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,g.state.pending_choice.id,('bad',)))
        self.assertEqual(g.snapshot(),saved)
        for game in(g,other):game.apply(SelectChoice(1,game.state.pending_choice.id,('ok',)))
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.hand(g)[0].id,card.id);self.portable(g)

    def test_full_hand_burns_actual_buffed_created_card(self):
        g=self.game(hand=(GUY,)+(YETI,)*9,mode='fill');source=self.play(g);self.pick(g)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertFalse(self.hand(g));burn,=[e for e in g.events if e.kind=='card_burned'];card=g.state.entities[burn.target_id]
        self.assertEqual((card.card_id,card.attack,card.max_health),(TAUNT,4,7));self.assertTrue(any(e.source_id==source for e in card.enchantments));self.portable(g)

    def test_full_board_has_no_effect_on_hand_grant_delivery(self):
        g=self.game(board=(YETI,)*7);self.play(g);self.pick(g);self.assertEqual((self.hand(g)[0].attack,self.hand(g)[0].max_health),(4,7));self.assertEqual(len(g.state.players[1].board),7);self.portable(g)

    def test_acquisition_failure_rolls_back_created_entity_and_attachment_and_selection(self):
        g=self.game(mode='fail');self.play(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.pick(g)
        self.assertEqual(g.snapshot(),saved)

    def test_empty_pool_consumes_no_rng_or_new_attachment(self):
        g=self.game(members=(YETI,));rng=g._rng.getstate();attachment=g.state.next_attachment_id;self.play(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.next_attachment_id,attachment);self.assertFalse(self.hand(g));self.portable(g)

    def test_missing_context_pool_or_unknown_eligible_taunt_fails_before_rng(self):
        for pool,context,members in((False,CTX,MEMBERS),(True,None,MEMBERS),(True,CTX,(TAUNT,UNKNOWN))):
            with self.subTest(pool=pool,context=context):
                g=self.game(pool=pool,context=context,members=members);saved=g.snapshot()
                with patch('random.Random.randrange',side_effect=AssertionError('RNG before complete eligibility'))as rng:
                    with self.assertRaises((ValueError,ResolutionError)):self.play(g)
                    rng.assert_not_called()
                self.assertEqual(g.snapshot(),saved)

    def test_actual_auto_cast_gets_buffed_card_without_generated_spell_payment(self):
        g=self.game(hand=(P+'auto',),members=(TAUNT,));self.play(g,P+'auto');self.assertIsNone(g.state.pending_choice);self.assertEqual(g.state.players[1].mana,20)
        card,=self.hand(g);self.assertEqual((card.attack,card.max_health),(4,7));self.portable(g)

    def test_finite_grant_declaration_rejects_unrelated_or_missing_material(self):
        g=self.game();self.play(g);spec=g._frame.options[0].effects[0].batch.spec
        bad=[dict(minion_grant=(1,2)),dict(minion_grant=CreatedMinionGrant(attack=-1)),dict(minion_grant=CreatedMinionGrant(keywords=(Keyword.TAUNT,))),dict(minion_grant=CreatedMinionGrant(attack=1,identity='other')),
             dict(source_id=None),dict(destination='board'),dict(discoveries=2),dict(delivery='after_all'),dict(cost=CostSpec(delta=-1)),dict(expires_turn=1),dict(query=replace(spec.query,kinds=(CardType.SPELL,))),dict(summon_copy_stats=SummonStats(2,3))]
        for changes in bad:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):replace(spec,**changes)
        self.assertIsNone(DiscoverFromPool(1,POOL_ID).minion_grant)
        from hs_sim.engine.hand_choice_followups import DiscoverForPlayFollowup
        with self.assertRaises(ValueError):DiscoverForPlayFollowup(spec)

    def test_frame_codec_rejects_illegal_nested_grant_without_repairing_input(self):
        g=self.game();self.play(g);branch=g._frame.options[0].effects[0];codec=FrameCodec(g.mechanics,g.registry);self.assertEqual(codec.decode(codec.encode(branch)),branch)
        encoded=codec.encode(branch)
        def mutate(value):
            if type(value)is dict:
                if value.get('type','').endswith('CreatedMinionGrant'):
                    value['fields']['attack']=-1;return True
                return any(mutate(v)for v in value.values())
            if type(value)is list:return any(mutate(v)for v in value)
            return False
        # Declared values already reject malformed shapes; this also traverses
        # the real encoded extension rather than fabricating a second codec.
        self.assertTrue(mutate(encoded))
        with self.assertRaises((ValueError,SnapshotError)):codec.decode(encoded)

    def test_default_311_identity_and_old_schema325_are_explicit(self):
        from hs_sim.engine.representative import build_registry as defaults
        self.assertEqual(defaults().fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')
        g=self.game();saved=g.snapshot();self.assertGreaterEqual(SNAPSHOT_SCHEMA_VERSION,326);saved['schema_version']=325
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry(*self.config))

if __name__=='__main__':unittest.main()
