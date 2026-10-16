"""Real Temporary discovery/generation delegate to the physical hand lifetime."""
from dataclasses import replace
import json,random,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.temporary_pool_minion_cards import BIOME,TERROR,ROOTS,POOL_ID,QUERIES,load_batch
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,UseLocation,Zone
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import AddToHand,ChoiceOption,Destroy,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CostSpec,LimitedTriggerSpec,Rarity,TargetMode,TargetSpec
from hs_sim.engine.pools import DiscoverFromPool,GenerateFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.temporary_cards import CreateTemporaryCard,validate_temporary_frame
from hs_sim.targets import canonical_digest

P='k115.test.';KILL=P+'kill';ONE='JAIL_460';TWO='CORE_GVG_085';YETI='CORE_CS2_182'
FOREIGN=P+'foreign';UNKNOWN1=P+'unknown1';UNKNOWN2=P+'unknown2'
CTX=GenerationContext('k115-explicit-experiment','experimental');MEMBERS=(*ROOTS,ONE,TWO,YETI,FOREIGN)
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=(),factions=(),subtypes=())

def registry(members=MEMBERS,mode=None,pool=True):
    r=build_registry()
    for cid,cost,cls in((FOREIGN,1,CardClass.MAGE),(UNKNOWN1,1,CardClass.NEUTRAL),(UNKNOWN2,2,CardClass.NEUTRAL)):
        if cid in members:r.register_pool_card(PoolCard(cid,CardType.MINION,cost,CardMetadata(True,(cls,),Rarity.COMMON,tribes=(),factions=(),subtypes=())))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'k115-complete-explicit-v1',CTX.target_id,CTX.mode,tuple(PoolMember(c)for c in members),complete=True))
    r.register_behavior(KILL,lambda c:(Destroy(c.target_id,c.source_id),))
    r.register_card(CardDefinition(KILL,'Destroy original minion',CardType.SPELL,on_play=KILL,metadata=META,
        targeting=TargetSpec(TargetMode.REQUIRED,zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='any')))
    r.register_behavior(P+'fail',lambda c:(_ for _ in()).throw(ResolutionError('K115 deliberate creation failure')))
    if mode:
        def eligible(c):
            if c.event.source_id is None or c.state.entities[c.event.source_id].card_id not in ROOTS:return False
            if mode=='fail_second':return sum(e.origin_entity_id==c.event.source_id and e.hand_lifetime is not None for e in c.state.entities.values())==2
            return True
        def watch(c):
            if mode=='fill':return(AddToHand(1,YETI,c.source_id),)
            if mode=='fail_second':return(InvokeBehavior(P+'fail',c.source_id,1),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(P+'watch',watch);r.register_trigger_condition(P+'eligible',eligible)
        r.register_card(CardDefinition(P+'watch','Actual Temporary creation reaction',CardType.MINION,health=5,metadata=META,
            limited_triggers=(LimitedTriggerSpec('choice_selected'if mode=='fill'else'card_created',P+'watch',condition_id=P+'eligible'),)))
    r.validate();return r

class TemporaryPoolMinionTests(unittest.TestCase):
    def game(self,hand=(BIOME,),board=(),enemy_hand=(),members=MEMBERS,mode=None,pool=True,context=CTX):
        self.config=(members,mode,pool)
        if mode:board=(*board,P+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_07',hand=hand,board=board,deck=(YETI,)*8,mana=20,max_mana=20,mana_cap=20),
            PlayerSetup('HERO_08',hand=enemy_hand,deck=(YETI,)*8,mana=20,max_mana=20,mana_cap=20)),seed=115,generation_context=context),registry(*self.config))
    def first(self,g,cid,zone='hand',player=1):return next(g.state.entities[i]for i in getattr(g.state.players[player],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None,player=1):
        eid=self.first(g,cid,player=player).id;kind=g.registry.card(cid).kind
        g.apply(PlayCard(player,eid,target,len(g.state.players[player].board)if kind in(CardType.MINION,CardType.LOCATION)else None));return eid
    def activate(self,g):
        source=self.play(g,BIOME);g.apply(UseLocation(1,source));return source
    def pick(self,g):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(q.options[0].id,)))
    def created(self,g,source):return[g.state.entities[e.target_id]for e in g.events if e.kind=='card_created'and e.source_id==source]
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(*self.config));self.assertEqual(other.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for field in('temporary_until_turn','resolution_frame','rng_state','pool_id','behavior_id'):self.assertNotIn('"'+field+'"',public)
        return other

    def test_two_complete_raw_rows_four_primary_faces_and_native_entry_metadata(self):
        data=load_batch();r=registry();self.assertEqual(len(data['cards']),2);self.assertEqual(len(data['official_observations']['observations']),4)
        norm=lambda s:re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in data['cards']:
            raw=row['record'];c=r.card(raw['id']);self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(c.metadata,metadata_from_record(raw));self.assertFalse(c.keywords)
            for o in(o for o in data['official_observations']['observations']if o['card_id']==c.id):
                en=o['locale']=='en_US';f=o['face'];self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']))
        self.assertEqual((r.card(BIOME).kind,r.card(BIOME).cost,r.card(BIOME).durability),(CardType.LOCATION,1,2));self.assertTrue(r.card(BIOME).on_use);self.assertFalse(r.card(BIOME).on_play)
        self.assertEqual((r.card(TERROR).cost,r.card(TERROR).attack,r.card(TERROR).health),(3,4,3));self.assertTrue(r.card(TERROR).deathrattle);self.assertFalse(r.card(TERROR).battlecry)
        self.assertEqual(tuple(r.card(TERROR).metadata.tribes),('beast',));self.assertFalse(data['cn_calibrated']);self.assertFalse(data['formal_pool_complete'])

    def test_native_location_uses_once_and_creates_temporary_one_cost_only(self):
        g=self.game();source=self.activate(g);self.assertEqual({o.card_id for o in g.state.pending_choice.options},{ONE});self.pick(g)
        card,=self.created(g,source);self.assertEqual((card.card_id,card.hand_lifetime.source_id,card.hand_lifetime.created_turn,card.hand_lifetime.expires_turn),(ONE,source,1,1))
        self.assertEqual(card.hand_lifetime.minimum_cost,0);self.assertEqual(g.state.entities[source].durability,1);self.assertEqual(g.state.players[1].mana,19);self.assertFalse(g.state.discard_history);self.portable(g)

    def test_temporary_expires_at_turn_end_without_discard_death_or_corpse(self):
        g=self.game();source=self.activate(g);self.pick(g);card,=self.created(g,source);old_deaths=len(g.state.death_history);g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[card.id].zone,Zone.GRAVEYARD);self.assertIsNone(g.state.entities[card.id].hand_lifetime);self.assertFalse(g.state.discard_history);self.assertEqual(len(g.state.death_history),old_deaths)
        self.assertEqual([e.target_id for e in g.events if e.kind=='card_expired'],[card.id]);self.portable(g)

    def test_old_same_face_hand_card_has_no_temporary_deadline(self):
        g=self.game(hand=(BIOME,ONE));old=self.first(g,ONE).id;source=self.activate(g);self.pick(g);new,=self.created(g,source);self.assertNotEqual(old,new.id);g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[old].zone,Zone.HAND);self.assertIsNone(g.state.entities[old].hand_lifetime);self.assertEqual(g.state.entities[new.id].zone,Zone.GRAVEYARD)

    def test_played_temporary_minion_is_not_destroyed_at_hand_expiry(self):
        g=self.game();source=self.activate(g);self.pick(g);card,=self.created(g,source);self.play(g,ONE);g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[card.id].zone,Zone.BOARD);self.assertIsNone(g.state.entities[card.id].hand_lifetime);self.assertFalse([e for e in g.events if e.kind=='card_expired'and e.target_id==card.id]);self.portable(g)

    def test_full_hand_choice_reaction_burns_actual_temporary_creation(self):
        g=self.game(hand=(BIOME,)+(YETI,)*9,mode='fill');source=self.activate(g);self.pick(g);card,=self.created(g,source)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(card.zone,Zone.GRAVEYARD);self.assertEqual(card.hand_lifetime.expires_turn,1);self.assertTrue(any(e.kind=='card_burned'and e.target_id==card.id for e in g.events));self.portable(g)

    def test_discovery_waiting_restore_freezes_offer_payment_and_rng(self):
        g=self.game();self.activate(g);other=self.portable(g);rng=g._rng.getstate()
        for game in(g,other):self.pick(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.players[1].mana,19);self.portable(g)

    def test_tunnel_native_deathrattle_creates_two_distinct_printed_two_cost_cards(self):
        g=self.game(hand=(KILL,),board=(TERROR,));source=self.first(g,TERROR,'board').id;self.play(g,KILL,source);cards=self.created(g,source)
        self.assertEqual([e.card_id for e in cards],[TWO,TWO]);self.assertEqual(len({e.id for e in cards}),2);self.assertTrue(all(e.hand_lifetime.expires_turn==1 and e.hand_lifetime.source_id==source for e in cards));self.assertEqual(len(g.state.death_history),1);self.assertFalse(g.state.battlecry_history);self.portable(g)

    def test_opponent_turn_death_uses_that_turn_deadline_and_owner_hand(self):
        g=self.game(hand=(),board=(TERROR,),enemy_hand=(KILL,));source=self.first(g,TERROR,'board').id;g.apply(EndTurn(1));self.play(g,KILL,source,2);cards=self.created(g,source)
        self.assertEqual(len(cards),2);self.assertTrue(all(e.controller==1 and e.hand_lifetime.expires_turn==2 for e in cards));self.assertEqual([g.state.entities[i].card_id for i in g.state.players[2].hand],[YETI]);self.portable(g);g.apply(EndTurn(2));self.assertTrue(all(g.state.entities[e.id].zone==Zone.GRAVEYARD for e in cards))

    def test_two_preselected_results_restore_at_first_creation_without_resampling(self):
        g=self.game(hand=(KILL,),board=(TERROR,),mode='wait');source=self.first(g,TERROR,'board').id;self.play(g,KILL,source);self.assertEqual(len(self.created(g,source)),1);self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);rng=g._rng.getstate();saved=g.snapshot()
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,g.state.pending_choice.id,('bad',)))
        self.assertEqual(g.snapshot(),saved)
        for game in(g,other):
            while game.state.pending_choice:game.apply(SelectChoice(1,game.state.pending_choice.id,('ok',)))
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g._rng.getstate(),rng);self.assertEqual(len(self.created(g,source)),2);self.portable(g)

    def test_second_creation_failure_rolls_back_death_two_results_and_rng(self):
        g=self.game(hand=(KILL,),board=(TERROR,),mode='fail_second');saved=g.snapshot();source=self.first(g,TERROR,'board').id
        with self.assertRaises(ResolutionError):self.play(g,KILL,source)
        self.assertEqual(g.snapshot(),saved)

    def test_tunnel_full_hand_delivers_then_burns_independent_temporary_card(self):
        g=self.game(hand=(KILL,)+(YETI,)*9,board=(TERROR,));source=self.first(g,TERROR,'board').id;self.play(g,KILL,source);cards=self.created(g,source)
        self.assertEqual([e.zone for e in cards],[Zone.HAND,Zone.GRAVEYARD]);self.assertTrue(all(e.hand_lifetime is not None for e in cards));self.portable(g)

    def test_unknown_or_missing_context_rolls_back_native_use_or_original_death_before_rng(self):
        for source,unknown in((BIOME,UNKNOWN1),(TERROR,UNKNOWN2)):
            for mode in('unknown','context','pool'):
                with self.subTest(source=source,mode=mode):
                    g=self.game(hand=(BIOME,)if source==BIOME else(KILL,),board=()if source==BIOME else(TERROR,),members=(*MEMBERS,unknown)if mode=='unknown'else MEMBERS,context=None if mode=='context'else CTX,pool=mode!='pool')
                    eid=self.play(g,BIOME)if source==BIOME else self.first(g,TERROR,'board').id;saved=g.snapshot()
                    with patch.object(random.Random,'randrange',side_effect=AssertionError('Unknown before Temporary request RNG'))as calls:
                        with self.assertRaises(ResolutionError):
                            if source==BIOME:g.apply(UseLocation(1,eid))
                            else:self.play(g,KILL,eid)
                        calls.assert_not_called()
                    self.assertEqual(g.snapshot(),saved)

    def test_empty_pools_are_rng_neutral_and_keep_native_use_and_death(self):
        for cid in ROOTS:
            with self.subTest(cid=cid):
                g=self.game(hand=(BIOME,)if cid==BIOME else(KILL,),board=()if cid==BIOME else(TERROR,),members=(YETI,));rng=g._rng.getstate()
                if cid==BIOME:source=self.activate(g)
                else:source=self.first(g,TERROR,'board').id;self.play(g,KILL,source)
                self.assertFalse(self.created(g,source));self.assertIsNone(g.state.pending_choice);self.assertEqual(g._rng.getstate(),rng);self.portable(g)

    def test_finite_declaration_rejects_cost_expiry_aliases_and_unimplemented_shapes(self):
        d=DiscoverFromPool(1,POOL_ID,QUERIES[BIOME],source_id=1,temporary_until_turn=1);z=GenerateFromPool(1,POOL_ID,QUERIES[TERROR],count=2,source_id=1,temporary_until_turn=1)
        for spec in(d,z):
            for change in({'temporary_until_turn':True},{'temporary_until_turn':0},{'source_id':None},{'destination':'deck'},{'cost':CostSpec(delta=0)},{'expires_turn':1},{'replacement':False}):
                with self.subTest(spec=type(spec).__name__,change=change):
                    with self.assertRaises(ValueError):replace(spec,**change)
        with self.assertRaises(ValueError):replace(d,minion_grant=CreatedMinionGrant(attack=1))
        from hs_sim.engine.hand_choice_followups import DiscoverForPlayFollowup
        with self.assertRaises(ValueError):DiscoverForPlayFollowup(d)
        from hs_sim.engine.pools import deliver_generated
        self.assertEqual(deliver_generated(d,(ONE,)),(CreateTemporaryCard(1,ONE,1,source_id=1),));self.assertIsNone(DiscoverFromPool(1,POOL_ID).temporary_until_turn)

    def test_real_frame_codec_and_boundary_reject_wrong_temporary_deadline(self):
        g=self.game();self.activate(g);branch=g._frame.options[0].effects[0];codec=FrameCodec(g.mechanics,g.registry);self.assertEqual(codec.decode(codec.encode(branch)),branch)
        s=json.loads(json.dumps(g.snapshot()));changed=[]
        def mutate(value):
            if type(value)is dict:
                fields=value.get('fields',{})
                if value.get('type','').endswith('DiscoverFromPool')and fields.get('temporary_until_turn')==1:fields['temporary_until_turn']=2;changed.append(True)
                for v in value.values():mutate(v)
            elif type(value)is list:
                for v in value:mutate(v)
        mutate(s);self.assertTrue(changed)
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry(*self.config))
        bad=g.clone();option=replace(bad._frame.options[0],effects=(replace(branch,batch=replace(branch.batch,spec=replace(branch.batch.spec,temporary_until_turn=2))),));bad._frame=replace(bad._frame,options=(option,*bad._frame.options[1:]))
        with self.assertRaises(ValueError):validate_temporary_frame(bad)

    def test_default_311_identity_and_old_schema326_rejection(self):
        from hs_sim.engine.representative import build_registry as defaults
        r=defaults();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667');self.assertGreaterEqual(SNAPSHOT_SCHEMA_VERSION,327)
        g=self.game();s=g.snapshot();s['schema_version']=326
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry(*self.config))

if __name__=='__main__':unittest.main()
