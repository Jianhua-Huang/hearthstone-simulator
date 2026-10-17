"""Native held-Dragon gate, spell damage, and unchanged complete gift pairing."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from dataclasses import asdict
import json,random,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p37_cards import RIDER,SUFFUSION,ROOTS,DEPENDENCIES,QUERIES,POOL_ID,load_batch,register_simple_followup_p37_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,Game,IllegalAction,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,SpellSchool,TargetSpec,Zone
from hs_sim.engine.dark_gifts import DARK_GIFTS,DARK_GIFT_VERSION,dark_gift_pool,public_gifts
from hs_sim.engine.effects import AddToHand,ChoiceOption,Damage,InvokeBehavior,RequestChoice,Summon
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import DamageKind,LimitedTriggerSpec,TribeChangeSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

TEST='p37.test.';DRAGON='EDR_889';BRIGHT='CORE_EX1_189';WARRIOR='TIME_871';DUAL='END_019';ALL='DINO_435';YETI='CORE_CS2_182';FOREIGN='TIME_033';SHIELD='CORE_GVG_085'
MEMBERS=(DRAGON,BRIGHT,WARRIOR,DUAL,ALL,YETI,FOREIGN)
CONTEXT=GenerationContext('p37-explicit-host-a','experimental');CONTEXT_B=GenerationContext('p37-explicit-host-b','experimental');META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    if not all(cid in r.cards for cid in ROOTS):register_simple_followup_p37_cards(r)
    register_candidate_pool_metadata(r);r.validate();return r

def registry(members=MEMBERS,mode=None,pool=True,context=CONTEXT):
    r=batch_registry()
    for cid in members:
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p37-complete-explicit-fixture-v1',context.target_id,context.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    def tribes(c,operation):return(ChangeMinionTribes(CardReference.capture(c.state.entities[c.target_id]),TribeChangeSpec(operation,('dragon',)),c.source_id),)
    scripts={'dragon':lambda c:tribes(c,'set'),'exclude':lambda c:tribes(c,'remove'),'natural':lambda c:(Summon(c.player_id,RIDER),),'wound':lambda c:(Damage(c.state.players[2].hero_id,28,c.source_id),),'counter':lambda c:(SetSecret(2,'EX1_287'),),'fail':lambda c:(_ for _ in()).throw(ResolutionError('P37 deliberate original continuation failure'))}
    for name,fn in scripts.items():
        r.register_behavior(TEST+name,fn);r.register_card(CardDefinition(TEST+name,name,CardType.SPELL,on_play=TEST+name,metadata=META,targeting=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,))if name in('dragon','exclude')else None))
    r.register_card(CardDefinition(TEST+'power','Ordinary spell damage',CardType.MINION,health=6,spell_damage=1,metadata=META))
    if mode:
        def eligible(c):
            if mode=='damage_wait':
                result=health_result(c.event);return result is not None and result.source_card_id==SUFFUSION
            return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id in ROOTS
        def watch(c):
            if mode=='fail':return(InvokeBehavior(TEST+'fail',c.source_id,1),)
            if mode=='fill':return(AddToHand(1,YETI,c.source_id),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible)
        r.register_card(CardDefinition(TEST+'watch','Actual native outcome reaction',CardType.MINION,health=9,metadata=META,limited_triggers=(LimitedTriggerSpec('health_resolved'if mode=='damage_wait'else'choice_selected'if mode=='fill'else'card_created',TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

class SimpleFollowupP37Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),members=MEMBERS,mode=None,pool=True,context=CONTEXT,supplied_context=True,hero='HERO_01'):
        self.config=(members,mode,pool,context)
        if mode:board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=(YETI,)*6,mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*6)),seed=3737,generation_context=context if supplied_context else None),registry(*self.config))
    def first(self,g,cid,zone='hand'):return next(g.state.entities[i]for i in getattr(g.state.players[1],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.first(g,cid).id;g.apply(PlayCard(1,eid,target,position=len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def options(self,g):return g._frame.options
    def spec(self,g):return self.options(g)[0].effects[0].batch.spec
    def pick(self,g,destination='hand'):return next(o for o in self.options(g)if o.effects[0].selection.gift.destination==destination)
    def choose(self,g,option=None,key=None):
        q=g.state.pending_choice;selected=key if key is not None else(option or self.pick(g)).id;g.apply(SelectChoice(q.player_id,q.id,(selected,)))
    def created(self,g,source):return[g.state.entities[e.target_id]for e in g.events if e.kind=='card_created'and e.source_id==source]
    def actual(self,g,cid):return resolve_candidates(g.registry,self.config[3],POOL_ID,QUERIES[cid],current_class=g.state.players[1].hero_class,source_card_id=cid,exclude_source_by_rule=True,player_id=1)
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(*self.config));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','pool_id','gift_pool','offered_gifts','behavior_id','DiscoveryGiftPool'):self.assertNotIn('"'+key+'"',public)
        return other

    def test_twelve_complete_rows_four_faces_exact_demon_warrior_fire_and_existing_recipes(self):
        d=load_batch();r=batch_registry();self.assertEqual(len(d['cards']+d['existing_gift_sources']),12);self.assertEqual(len(d['official_observations']['observations']),4);self.assertEqual(d['gift_version'],DARK_GIFT_VERSION);self.assertEqual(d['gift_recipes_sha256'],canonical_digest([asdict(g)for g in DARK_GIFTS]));self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])
        norm=lambda s:re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']+d['existing_gift_sources']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        for row in d['cards']:
            raw=row['record'];c=r.card(raw['id']);self.assertEqual(c.metadata,metadata_from_record(raw));self.assertEqual(c.metadata.classes,(CardClass.WARRIOR,));self.assertEqual(c.cost,raw['cost']);self.assertFalse(c.keywords)
            for o in(o for o in d['official_observations']['observations']if o['card_id']==raw['id']):
                f=o['face'];en=o['locale']=='en_US';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']));self.assertEqual((f['id'],f['manaCost']),(raw['dbf_id'],raw['cost']));self.assertEqual(f['childIds'],[x['record']['dbf_id']for x in d['existing_gift_sources']])
        self.assertEqual(r.card(RIDER).metadata.tribes,('demon',));self.assertEqual((r.card(RIDER).attack,r.card(RIDER).health),(1,1));self.assertIsNone(r.card(RIDER).spell_school);self.assertIsNotNone(r.card(RIDER).battlecry);self.assertEqual(r.card(SUFFUSION).spell_school,SpellSchool.FIRE)

    def test_only_two_new_definitions_preserve_old_pool_metadata_and_generation_families(self):
        with patch('hs_sim.cards.simple_followup_p37_cards.register_simple_followup_p37_cards',lambda r:None):before=build_registry()
        after=batch_registry();self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS));self.assertFalse(DEPENDENCIES);self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards));self.assertEqual(dict(before.pool_cards),dict(after.pool_cards));self.assertEqual(dict(before.generation_families),dict(after.generation_families));self.assertEqual(dict(before.pools),dict(after.pools))
        self.assertTrue(all(g.id not in after.cards and g.id not in after.pool_cards for g in DARK_GIFTS))

    def test_default311_and_no_production_formal_pool(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT);self.assertFalse(any(p.id==POOL_ID or p.mode=='standard'for p in batch_registry().pools.values()))

    def test_rider_no_own_hand_dragon_ignores_own_body_board_and_opponent_without_pool(self):
        g=self.game((RIDER,YETI),board=(DRAGON,),enemy=(DRAGON,),enemy_hand=(DRAGON,),pool=False,supplied_context=False);rng=g._rng.getstate()
        with patch.object(random.Random,'randrange',side_effect=AssertionError('False gate sampled'))as samples:
            with patch.object(random.Random,'choice',side_effect=AssertionError('False gate picked gift'))as gifts:source=self.play(g,RIDER);samples.assert_not_called();gifts.assert_not_called()
        self.assertIsNone(g.state.pending_choice);self.assertFalse(self.created(g,source));self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.players[1].mana,49);self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)

    def test_rider_all_tribe_held_minion_unlocks_and_current_exclusion_removes_gate(self):
        g=self.game((RIDER,ALL),members=(DRAGON,));self.play(g,RIDER);self.assertIsNotNone(g.state.pending_choice);self.choose(g)
        g=self.game((TEST+'exclude',RIDER,ALL),pool=False,supplied_context=False);self.play(g,TEST+'exclude',self.first(g,ALL).id);self.play(g,RIDER);self.assertIsNone(g.state.pending_choice)

    def test_rider_uses_current_granted_hand_dragon_not_only_printed_tribe(self):
        g=self.game((TEST+'dragon',RIDER,YETI),members=(DRAGON,));self.play(g,TEST+'dragon',self.first(g,YETI).id);self.play(g,RIDER);self.assertIsNotNone(g.state.pending_choice);self.choose(g);self.portable(g)

    def test_rider_current_hero_plus_neutral_dragon_minions_not_source_printed_class(self):
        for hero,expected in(('HERO_01',{DRAGON,BRIGHT,WARRIOR,ALL}),('HERO_06',{DRAGON,BRIGHT,ALL})):
            with self.subTest(hero=hero):
                g=self.game((RIDER,DRAGON),hero=hero);self.assertEqual({m.card_id for m in self.actual(g,RIDER)},expected);self.play(g,RIDER);self.assertTrue({o.card_id for o in g.state.pending_choice.options}<=expected);self.assertEqual(self.spec(g).query,QUERIES[RIDER]);self.choose(g)

    def test_rider_paid_native_battlecry_distinct_gifts_preview_and_new_entity_only(self):
        g=self.game((RIDER,DRAGON),members=(DRAGON,));old=self.first(g,DRAGON).id;source=self.play(g,RIDER);options=self.options(g);self.assertEqual(len(options),1);self.assertEqual(len({o.effects[0].selection.gift.id for o in options}),1);option=self.pick(g);gift=option.effects[0].selection.gift;self.assertTrue(gift.eligible(g.registry.card(option.card_id)));self.choose(g,option);new,=self.created(g,source);self.assertNotEqual(new.id,old);self.assertEqual((new.card_id,new.cost,new.attack,new.max_health),(option.card_id,option.preview.cost,option.preview.attack,option.preview.max_health));self.assertEqual(public_gifts(new),[{'id':gift.id,'name':gift.label}]);self.assertFalse(public_gifts(g.state.entities[old]));self.assertEqual((len(g.state.battlecry_history),len(g.state.cast_history),g.state.players[1].mana),(1,0,49));self.portable(g)

    def test_actual_host_targets_bind_same_complete_ten_gifts_without_card_target_constants(self):
        for ctx in(CONTEXT,CONTEXT_B):
            with self.subTest(target=ctx.target_id):
                g=self.game((RIDER,DRAGON),members=(DRAGON,),context=ctx);self.play(g,RIDER);self.assertEqual(self.spec(g).gift_pool,dark_gift_pool(ctx.target_id,ctx.mode));self.assertEqual(self.spec(g).gift_pool.members,DARK_GIFTS);self.assertTrue(self.spec(g).gift_pool.complete);self.portable(g)

    def test_gift_offer_restore_clone_independent_replay_keeps_pair_rng_and_single_payment(self):
        g=self.game((RIDER,DRAGON),members=(DRAGON,));source=self.play(g,RIDER);option=self.pick(g);self.assertEqual(g.observe(2)['pending_choice'],{'player_id':1});rng=g._rng.getstate();other=self.portable(g)
        for game in(g,other):self.choose(game,option)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g._rng.getstate(),rng);self.assertEqual(len(self.created(g,source)),1);self.assertEqual(g.state.players[1].mana,49);self.portable(g)

    def test_suffusion_ordinary_required_character_targets_validate_before_payment(self):
        g=self.game((SUFFUSION,),board=(YETI,),enemy=(YETI,));source=self.first(g,SUFFUSION).id;targets={g.state.players[1].hero_id,g.state.players[2].hero_id,*g.state.players[1].board,*g.state.players[2].board};self.assertEqual(set(g.legal_targets(source)),targets)
        for target in(None,source):
            saved=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,SUFFUSION,target)
            self.assertEqual(g.snapshot(),saved)

    def test_suffusion_spell_damage_bonus_precedes_fixed_warrior_pool_even_on_other_hero(self):
        g=self.game((SUFFUSION,),board=(TEST+'power',),hero='HERO_08');hero=g.state.players[2].hero_id;self.assertEqual({m.card_id for m in self.actual(g,SUFFUSION)},{WARRIOR,DUAL});source=self.play(g,SUFFUSION,hero);self.assertEqual(g.state.entities[hero].health,27);results=[health_result(e)for e in g.events if e.kind=='health_resolved'and health_result(e).source_id==source];self.assertEqual((results[0].damage_dealt,results[0].damage_kind),(3,DamageKind.SPELL.value));self.assertTrue({o.card_id for o in g.state.pending_choice.options}<={WARRIOR,DUAL});self.assertEqual(self.spec(g).query,QUERIES[SUFFUSION]);self.choose(g);self.assertEqual((g.state.players[1].mana,len(g.state.cast_history),len(g.state.battlecry_history)),(48,1,0));self.portable(g)

    def test_suffusion_absorbed_damage_still_discovers_without_success_or_kill_gate(self):
        g=self.game((SUFFUSION,),board=(SHIELD,),members=(DUAL,));victim=g.state.players[1].board[0];self.play(g,SUFFUSION,victim);self.assertEqual(g.state.entities[victim].health,2);self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[victim].keywords);self.assertIsNotNone(g.state.pending_choice);self.choose(g);self.portable(g)

    def test_suffusion_minion_death_is_resolved_before_discovery_and_terminal_stops_queue(self):
        g=self.game((SUFFUSION,),enemy=(RIDER,),members=(DUAL,));victim=g.state.players[2].board[0];self.play(g,SUFFUSION,victim);self.assertEqual(g.state.entities[victim].zone,Zone.GRAVEYARD);self.assertIsNotNone(g.state.pending_choice);self.choose(g)
        g=self.game((TEST+'wound',SUFFUSION),pool=False,supplied_context=False);self.play(g,TEST+'wound');self.play(g,SUFFUSION,g.state.players[2].hero_id);self.assertEqual((g.state.status,g.state.winner),('finished',1));self.assertIsNone(g.state.pending_choice)

    def test_suffusion_countered_spell_has_no_damage_or_discovery_request(self):
        g=self.game((TEST+'counter',SUFFUSION),pool=False,supplied_context=False);self.play(g,TEST+'counter');source=self.play(g,SUFFUSION,g.state.players[2].hero_id);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30);self.assertIsNone(g.state.pending_choice);self.assertFalse(self.created(g,source));self.assertEqual(g.state.cast_history[-1].failure,'countered');self.assertEqual(g.state.players[1].mana,48)

    def test_suffusion_actual_damage_wait_restores_before_host_gift_binding_and_bad_resume(self):
        g=self.game((SUFFUSION,),members=(DUAL,),mode='damage_wait');hero=g.state.players[2].hero_id;self.play(g,SUFFUSION,hero);self.assertEqual(g.state.entities[hero].health,28);self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,key='bad')
        self.assertEqual(g.snapshot(),saved)
        for game in(g,other):self.choose(game,key='ok')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.spec(g).gift_pool,dark_gift_pool(CONTEXT.target_id,CONTEXT.mode));self.portable(g)

    def test_selected_gift_creation_failure_rolls_back_only_selection_not_paid_damage(self):
        for cid in ROOTS:
            with self.subTest(cid=cid):
                g=self.game((cid,DRAGON)if cid==RIDER else(cid,),members=(DRAGON,)if cid==RIDER else(DUAL,),mode='fail');self.play(g,cid,None if cid==RIDER else g.state.players[2].hero_id);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.choose(g,self.pick(g))
                self.assertEqual(g.snapshot(),saved);self.assertEqual(g.state.players[1].mana,49 if cid==RIDER else 48);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30 if cid==RIDER else 28);self.portable(g)

    def test_full_hand_burn_keeps_actual_complete_selected_gift_material(self):
        g=self.game((RIDER,DRAGON)+(YETI,)*8,members=(DRAGON,),mode='fill');source=self.play(g,RIDER);option=self.pick(g);self.choose(g,option);new,=self.created(g,source);self.assertEqual(new.zone,Zone.GRAVEYARD);self.assertEqual((new.cost,new.attack,new.max_health),(option.preview.cost,option.preview.attack,option.preview.max_health));self.assertEqual(len([e for e in g.events if e.kind=='card_burned']),1);self.portable(g)

    def test_natural_summon_rider_with_held_dragon_does_not_execute_battlecry(self):
        g=self.game((TEST+'natural',DRAGON),pool=False,supplied_context=False);self.play(g,TEST+'natural');self.assertFalse(g.state.battlecry_history);self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_complete_unknown_candidates_fail_before_minion_and_gift_rng_roll_back_damage(self):
        for cid,unknown in((RIDER,'EDR_465'),(SUFFUSION,'CAP_104')):
            with self.subTest(cid=cid):
                g=self.game((cid,DRAGON)if cid==RIDER else(cid,),members=(*MEMBERS,unknown));saved=g.snapshot();self.assertNotIn(unknown,g.registry.cards)
                with patch.object(random.Random,'randrange',side_effect=AssertionError('Unknown minion sampled'))as samples:
                    with patch.object(random.Random,'choice',side_effect=AssertionError('Gift selected early'))as gifts:
                        with self.assertRaises(ResolutionError):self.play(g,cid,None if cid==RIDER else g.state.players[2].hero_id)
                        samples.assert_not_called();gifts.assert_not_called()
                self.assertEqual(g.snapshot(),saved)

    def test_true_discovery_missing_host_context_or_pool_rolls_back_both_entries(self):
        for cid in ROOTS:
            for missing in('context','pool'):
                with self.subTest(cid=cid,missing=missing):
                    g=self.game((cid,DRAGON)if cid==RIDER else(cid,),pool=missing!='pool',supplied_context=missing!='context');saved=g.snapshot()
                    with self.assertRaises(ResolutionError):self.play(g,cid,None if cid==RIDER else g.state.players[2].hero_id)
                    self.assertEqual(g.snapshot(),saved)

if __name__=='__main__':unittest.main()
