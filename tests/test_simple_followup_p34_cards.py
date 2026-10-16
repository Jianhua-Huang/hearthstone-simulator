"""Native P34 consumers, actual zone delivery and original continuation proofs."""
from dataclasses import asdict,replace
import json,random,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p34_cards import JACKPOT,SELLER,ASTRO,ATLAS,DRAKE,AEGIS,POWER,ROOTS,DEPENDENCIES,EXISTING_DEPENDENCIES,IDENTITIES,QUERIES,POOL_ID,load_batch,register_simple_followup_p34_cards
from hs_sim.engine import CardDefinition,CardMetadata,CardClass,CardType,EndTurn,Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,TargetSpec,UseHeroPower,Zone
from hs_sim.engine.effects import ChoiceOption,Destroy,InvokeBehavior,RequestChoice,Silence,Summon
from hs_sim.engine.end_turns import TriggerEndTurnEffects
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.imbue import imbue_count,imbue_value
from hs_sim.engine.model import EndTurnRequest,EndTurnSelector,LimitedTriggerSpec,SpellSchool
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery,resolve_candidates,sample_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest

TEST='p34.test.';YETI='CORE_CS2_182';TWO='BT_156';BRIGHT='CORE_EX1_189';DRAGON='EDR_889';TAUNT='CORE_KAR_061';FOUR='CORE_CS2_179';MAGE='CORE_CS2_028';OTHER='JAIL_913';DUAL='END_023';SMALL='TIME_000';NEUTRAL='TIME_EVENT_999'
MEMBERS=(*ROOTS,YETI,TWO,BRIGHT,DRAGON,TAUNT,FOUR,MAGE,OTHER,DUAL,SMALL,NEUTRAL)
CONTEXT=GenerationContext('p34-explicit-experiment','experimental');META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    if not all(cid in r.cards for cid in ROOTS):register_simple_followup_p34_cards(r)
    register_candidate_pool_metadata(r);r.validate();return r

def registry(members=MEMBERS,mode=None,pool=True):
    r=batch_registry()
    for cid in members:
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p34-complete-explicit-fixture-v1',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    def extra(c):return(TriggerEndTurnEffects(c.player_id,EndTurnRequest(EndTurnSelector('selected',(c.player_id,),('minion',),(c.target_id,))),c.source_id),)
    for name,fn in(('kill',lambda c:(Destroy(c.target_id,c.source_id),)),('silence',lambda c:(Silence(c.target_id),)),('extra',extra),('natural',lambda c:(Summon(c.player_id,ASTRO),)),('fail',lambda c:(_ for _ in()).throw(ResolutionError('P34 deliberate entry failure')))):
        r.register_behavior(TEST+name,fn);native={'kind':CardType.MINION,'attack':1,'health':1,'battlecry':TEST+name}if name in('extra','silence')else{'kind':CardType.SPELL,'on_play':TEST+name}
        r.register_card(CardDefinition(TEST+name,name,metadata=META,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if name in('kill','silence','extra')else None,**native))
    if mode:
        def eligible(c):return any(root.request.cause.source.card_id==AEGIS and any(d.outcome=='delivered'and d.entity.entity_id==c.event.target_id for d in root.deliveries)for root in c.state.card_summon_history)
        def watch(c):
            if Keyword.TAUNT not in c.state.entities[c.event.target_id].keywords or imbue_count(c.state,1):raise ResolutionError('Aegis entry reaction did not precede Imbue with Taunt installed')
            if mode=='fail':return(InvokeBehavior(TEST+'fail',c.source_id,1),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible)
        r.register_card(CardDefinition(TEST+'watch','Actual entry observer',CardType.MINION,health=9,metadata=META,limited_triggers=(LimitedTriggerSpec('minion_summoned',TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

class SimpleFollowupP34Tests(unittest.TestCase):
    def game(self,hand=(),board=(),members=MEMBERS,mode=None,pool=True,context=CONTEXT,hero='HERO_04'):
        self.config=(members,mode,pool)
        if mode:board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50)),seed=3434,generation_context=context),registry(*self.config))
    def first(self,g,cid,zone='hand'):return next(g.state.entities[i]for i in getattr(g.state.players[1],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.first(g,cid).id;g.apply(PlayCard(1,eid,target,len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def created(self,g,source):return[e for e in g.events if e.kind=='card_created'and e.source_id==source]
    def bodies(self,g,source):return[g.state.entities[d.entity.entity_id]for root in g.state.card_summon_history if root.request.cause.source.entity_id==source for d in root.deliveries if d.outcome=='delivered']
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(*self.config));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','pool_id','pool_basis','entry_keywords','card_summon_history','behavior_id'):self.assertNotIn('"'+key+'"',public)
        return other
    def actual(self,g,cid,query=None):return resolve_candidates(g.registry,CONTEXT,POOL_ID,query or QUERIES[cid],current_class=g.state.players[1].hero_class,source_card_id=cid,exclude_source_by_rule=True,player_id=1)

    def test_ten_complete_rows_twelve_faces_exact_metadata_display_suffix_and_power(self):
        d=load_batch();r=batch_registry();self.assertEqual(len(d['cards']+d['existing_dependencies']+d['evidence_only']),10);self.assertEqual(len(d['official_observations']['observations']),12);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated']);self.assertTrue(d['required_generation_context'])
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']:
            raw=row['record'];cid=raw['id'];c=r.card(cid);self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(c.metadata,replace(metadata_from_record(raw),deck_identity=IDENTITIES[cid]));self.assertEqual(c.cost,raw['cost']);self.assertEqual(c.keywords,(Keyword.TAUNT,)if cid==ATLAS else(Keyword.ELUSIVE,)if cid==DRAKE else())
            for o in(o for o in d['official_observations']['observations']if o['card_id']==cid):
                face=o['face'];en=o['locale']=='en_US';text=raw['text_en'if en else'text']
                if cid==DRAKE:self.assertTrue(text.endswith('~GAMEPLAY_ASPROXY_EDR_462'));text=text.removesuffix('~GAMEPLAY_ASPROXY_EDR_462')
                self.assertEqual(face['name'],raw['name_en'if en else'name']);self.assertEqual(norm(face['text']),norm(text));self.assertEqual((face['id'],face['manaCost']),(raw['dbf_id'],c.cost))
        self.assertEqual(r.card(SELLER).metadata.tribes,('naga',));self.assertEqual(r.card(ATLAS).metadata.tribes,('beast',));self.assertEqual(r.card(DRAKE).metadata.tribes,('dragon',));self.assertEqual(r.card(AEGIS).spell_school,SpellSchool.HOLY);self.assertEqual(d['reviewed_display_normalizations'],{DRAKE:{'~GAMEPLAY_ASPROXY_EDR_462':''}})
        dep,=d['existing_dependencies'];self.assertEqual(canonical_digest(asdict(r.card(POWER))),dep['definition_sha256']);self.assertEqual(canonical_digest(dep['definition']),dep['definition_sha256'])

    def test_six_new_complete_definitions_preserve_all_old_and_catalog_families(self):
        with patch('hs_sim.cards.simple_followup_p34_cards.register_simple_followup_p34_cards',lambda r:None):before=build_registry()
        after=batch_registry();self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS));self.assertFalse(DEPENDENCIES);self.assertEqual(EXISTING_DEPENDENCIES,(POWER,));self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards));self.assertEqual(dict(before.generation_families),dict(after.generation_families));self.assertEqual(dict(before.pools),dict(after.pools));self.assertEqual(set(before.pool_cards),set(after.pool_cards))
        for cid,c in before.pool_cards.items():self.assertEqual(replace(c,metadata=replace(c.metadata,deck_identity=IDENTITIES[cid]))if cid in ROOTS else c,after.pool_card(cid))

    def test_default311_and_production_formal_pools_unchanged(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667');self.assertFalse(any(p.id==POOL_ID or p.mode=='standard'for p in batch_registry().pools.values()))

    def test_jackpot_printed_five_floor_current_hero_other_classes_exclude_dual_and_neutral(self):
        for hero,expected in(('HERO_08',{OTHER}),('HERO_01',{MAGE,OTHER}),('HERO_04',{MAGE,OTHER,DUAL})):
            with self.subTest(hero=hero):
                g=self.game(members=(MAGE,OTHER,DUAL,SMALL,NEUTRAL),hero=hero);self.assertEqual({m.card_id for m in self.actual(g,JACKPOT)},expected)

    def test_jackpot_paid_two_independent_private_hand_copies_and_rng(self):
        g=self.game((JACKPOT,),members=(OTHER,),hero='HERO_08');rng=random.Random();rng.setstate(g._rng.getstate());sample_candidates(rng,self.actual(g,JACKPOT),2,replacement=True);source=self.play(g,JACKPOT);events=self.created(g,source);self.assertEqual([g.state.entities[e.target_id].card_id for e in events],[OTHER,OTHER]);self.assertEqual(len({e.target_id for e in events}),2);self.assertEqual(g.state.players[1].mana,48);self.assertEqual(g._rng.getstate(),rng.getstate());self.assertNotIn(OTHER,json.dumps(g.observe(2)));self.portable(g)

    def test_jackpot_full_hand_burns_second_copy(self):
        g=self.game((JACKPOT,)+(YETI,)*9,members=(OTHER,));source=self.play(g,JACKPOT);self.assertEqual(len(self.created(g,source)),2);self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len([e for e in g.events if e.kind=='card_burned']),1)

    def test_seller_extra_owner_end_puts_opponent_top_without_draw_or_shuffle(self):
        g=self.game((TEST+'extra',),board=(SELLER,),members=(OTHER,));seller=self.first(g,SELLER,'board').id;deck=list(g.state.players[2].deck);self.play(g,TEST+'extra',seller);event,=self.created(g,seller);new=g.state.entities[event.target_id];self.assertEqual((new.card_id,new.controller,new.zone),(OTHER,2,Zone.DECK));self.assertEqual(g.state.players[2].deck,[new.id,*deck]);self.assertFalse(g.state.draw_history);self.assertFalse(g.state.players[2].hand);self.assertEqual(g.state.active_player,1)
        for p in(1,2):
            self.assertNotIn(OTHER,json.dumps(g.observe(p)))
            for e in g.player_events(p):
                if e['kind']=='card_added_to_deck':self.assertIsNone(e['target'])
        self.portable(g)

    def test_seller_natural_owner_end_top_is_next_opponent_draw_and_not_opponent_end(self):
        g=self.game(board=(SELLER,),members=(OTHER,));seller=self.first(g,SELLER,'board').id;deck=list(g.state.players[2].deck);g.apply(EndTurn(1));event,=self.created(g,seller);self.assertEqual(g.state.players[2].hand,[event.target_id]);self.assertEqual(g.state.players[2].deck,deck);g.apply(EndTurn(2));self.assertEqual(len(self.created(g,seller)),1)

    def test_astro_native_battlecry_uses_post_play_hand_count_and_original_cause(self):
        g=self.game((ASTRO,YETI,YETI),members=(TWO,YETI));source=self.play(g,ASTRO);body,=self.bodies(g,source);self.assertEqual(body.card_id,TWO);self.assertEqual(g.state.players[1].mana,43);self.assertEqual(len(g.state.battlecry_history),1);root=g.state.card_summon_history[0];self.assertEqual(root.request.pool_basis.query.min_cost,2);self.assertEqual(root.request.pool_basis.query.max_cost,2);self.assertEqual(root.request.cause.source.entity_id,source);self.portable(g)

    def test_astro_zero_hand_pool_empty_does_not_use_preplay_one(self):
        g=self.game((ASTRO,),members=(TWO,));rng=g._rng.getstate();source=self.play(g,ASTRO);self.assertFalse(self.bodies(g,source));self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.players[1].board,[source])

    def test_astro_natural_summon_has_no_battlecry_or_pool_requirement(self):
        g=self.game((TEST+'natural',),pool=False,context=None);source=self.play(g,TEST+'natural');self.assertEqual(g.state.entities[g.state.players[1].board[0]].card_id,ASTRO);self.assertFalse(g.state.battlecry_history);self.assertFalse(self.created(g,source));self.portable(g)

    def test_astro_full_after_paid_entry_skips_own_rng(self):
        g=self.game((ASTRO,YETI,YETI),board=(YETI,)*6,members=(TWO,));rng=g._rng.getstate();source=self.play(g,ASTRO);self.assertFalse(self.bodies(g,source));self.assertEqual(g._rng.getstate(),rng);self.assertEqual(len(g.state.players[1].board),7)

    def test_atlas_exact_native_taunt_deathrattle_pool_not_dragon_name_or_grant(self):
        g=self.game((TEST+'kill',),board=(ATLAS,),members=(TAUNT,FOUR,TWO,ATLAS));atlas=self.first(g,ATLAS,'board').id;self.assertEqual({m.card_id for m in self.actual(g,ATLAS)},{TAUNT});self.play(g,TEST+'kill',atlas);body,=self.bodies(g,atlas);self.assertEqual(body.card_id,TAUNT);self.assertIn(Keyword.TAUNT,body.keywords);self.assertEqual(g.state.entities[atlas].zone,Zone.GRAVEYARD);self.assertFalse(g.state.battlecry_history);self.assertEqual(g.state.deathrattle_history[0].capture.ability.deathrattle_card_id,ATLAS);self.portable(g)

    def test_source_only_atlas_and_drake_are_empty_before_rng(self):
        for cid in(ATLAS,DRAKE):
            with self.subTest(cid=cid):
                key=TEST+('kill'if cid==ATLAS else'extra');g=self.game((key,),board=(cid,),members=(cid,));source=self.first(g,cid,'board').id;rng=g._rng.getstate()
                with patch.object(random.Random,'randrange',side_effect=AssertionError('Source sampled'))as calls:self.play(g,key,source);calls.assert_not_called()
                self.assertEqual(g._rng.getstate(),rng);self.assertFalse(self.created(g,source));self.assertFalse(self.bodies(g,source))

    def test_drake_native_elusive_owner_end_dragon_reward_any_class(self):
        g=self.game(board=(DRAKE,),members=(DRAGON,TWO));drake=self.first(g,DRAKE,'board').id;self.assertIn(Keyword.ELUSIVE,g.state.entities[drake].keywords);g.apply(EndTurn(1));event,=self.created(g,drake);self.assertEqual(g.state.entities[event.target_id].card_id,DRAGON);self.assertEqual(g.state.entities[event.target_id].zone,Zone.HAND);g.apply(EndTurn(2));self.assertEqual(len(self.created(g,drake)),1);self.portable(g)

    def test_drake_extra_end_body_and_silence_use_native_lifecycle(self):
        g=self.game((TEST+'extra',TEST+'silence',TEST+'extra'),board=(DRAKE,),members=(DRAGON,));drake=self.first(g,DRAKE,'board').id;self.play(g,TEST+'extra',drake);self.assertEqual(len(self.created(g,drake)),1);self.play(g,TEST+'silence',drake);self.assertNotIn(Keyword.ELUSIVE,g.state.entities[drake].keywords);self.play(g,TEST+'extra',drake);self.assertEqual(len(self.created(g,drake)),1)

    def test_aegis_non_taunt_exact_two_gets_preentry_grant_then_actual_paladin_power(self):
        g=self.game((AEGIS,),members=(BRIGHT,));oldpower=g.state.players[1].hero_power_id;source=self.play(g,AEGIS);body,=self.bodies(g,source);self.assertEqual(body.card_id,BRIGHT);self.assertNotIn(Keyword.TAUNT,g.registry.card(BRIGHT).keywords);self.assertIn(Keyword.TAUNT,body.keywords);self.assertTrue(any(a.kind=='keyword'and a.keyword==Keyword.TAUNT and a.source_id==source for a in body.abilities));self.assertFalse(g.state.battlecry_history);self.assertNotEqual(g.state.players[1].hero_power_id,oldpower);self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,POWER);self.assertEqual(imbue_count(g.state,1),1);self.assertEqual(g.state.imbue_history[0].source_id,source);self.assertEqual(g.state.card_summon_history[0].request.pool_basis.entry_keywords,(Keyword.TAUNT,));self.assertEqual(g.state.players[1].mana,48);self.portable(g)

    def test_aegis_unfiltered_two_pool_and_current_mage_or_no_growth_warrior(self):
        for hero,power in(('HERO_08','EDR_851p'),('HERO_01',None)):
            with self.subTest(hero=hero):
                g=self.game((AEGIS,),members=(TWO,),hero=hero);old=g.state.players[1].hero_power_id;self.assertFalse(QUERIES[AEGIS].keywords_all);self.play(g,AEGIS);self.assertEqual(imbue_count(g.state,1),1);self.assertEqual(imbue_count(g.state,1,applied_only=True),int(power is not None))
                if power:self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,power)
                else:self.assertEqual(g.state.players[1].hero_power_id,old)

    def test_aegis_subsequent_growth_keeps_power_and_real_power_inserts_two_portals(self):
        g=self.game((AEGIS,AEGIS),members=(TWO,));self.play(g,AEGIS);power=g.state.players[1].hero_power_id;self.play(g,AEGIS);self.assertEqual(g.state.players[1].hero_power_id,power);self.assertEqual(imbue_value(g.state,1),2);g.apply(UseHeroPower(1,power));portals=[i for i in g.state.players[1].deck if g.state.entities[i].card_id=='EDR_445pt3'];self.assertEqual(len(set(portals)),2);self.assertEqual(g.state.players[1].mana,45);self.assertEqual(imbue_count(g.state,1),2);self.portable(g)

    def test_aegis_full_board_and_empty_pool_skip_rng_but_still_imbue(self):
        for board,members in(((YETI,)*7,(TWO,)),((),(YETI,))):
            with self.subTest(full=bool(board)):
                g=self.game((AEGIS,),board=board,members=members);rng=g._rng.getstate();source=self.play(g,AEGIS);self.assertFalse(self.bodies(g,source));self.assertEqual(g._rng.getstate(),rng);self.assertEqual(imbue_count(g.state,1),1);self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,POWER);self.portable(g)

    def test_aegis_actual_entry_wait_before_imbue_restore_clone_replay_and_bad_resume(self):
        g=self.game((AEGIS,),members=(BRIGHT,),mode='wait');source=self.play(g,AEGIS);self.assertIsNotNone(g.state.pending_choice);self.assertIn(Keyword.TAUNT,self.bodies(g,source)[0].keywords);self.assertEqual(imbue_count(g.state,1),0);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,g.state.pending_choice.id,('bad',)))
        self.assertEqual(g.snapshot(),saved)
        for game in(g,other):game.apply(SelectChoice(1,game.state.pending_choice.id,('ok',)))
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(imbue_count(g.state,1),1);self.portable(g)

    def test_aegis_late_entry_failure_rolls_back_payment_grant_rng_and_imbue(self):
        g=self.game((AEGIS,),members=(BRIGHT,),mode='fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,AEGIS)
        self.assertEqual(g.snapshot(),saved)

    def test_unknown_eligible_candidates_fail_before_own_rng_and_rollback_all_native_paths(self):
        for cid,unknown in((JACKPOT,'BE_EVENT_102'),(SELLER,'BE_EVENT_102'),(ASTRO,'CAP_104'),(ATLAS,'EDR_258'),(DRAKE,'CATA_132'),(AEGIS,'CAP_104')):
            with self.subTest(cid=cid):
                hand=(TEST+'extra',)if cid in(SELLER,DRAKE)else(TEST+'kill',)if cid==ATLAS else(ASTRO,YETI,YETI)if cid==ASTRO else(cid,);g=self.game(hand,board=(cid,)if cid in(SELLER,DRAKE,ATLAS)else(),members=(*MEMBERS,unknown),hero='HERO_08');saved=g.snapshot();self.assertNotIn(unknown,g.registry.cards)
                with patch.object(random.Random,'randrange',side_effect=AssertionError('Unknown sampled'))as calls:
                    with self.assertRaises(ResolutionError):self.play(g,TEST+'extra',self.first(g,cid,'board').id)if cid in(SELLER,DRAKE)else self.play(g,TEST+'kill',self.first(g,cid,'board').id)if cid==ATLAS else self.play(g,cid)
                    calls.assert_not_called()
                self.assertEqual(g.snapshot(),saved)

    def test_aegis_full_board_still_rejects_unknown_candidate_before_rng_or_imbue(self):
        g=self.game((AEGIS,),board=(YETI,)*7,members=(TWO,'CAP_104'));saved=g.snapshot()
        with patch.object(random.Random,'randrange',side_effect=AssertionError('Unknown sampled'))as calls:
            with self.assertRaises(ResolutionError):self.play(g,AEGIS)
            calls.assert_not_called()
        self.assertEqual(g.snapshot(),saved)

    def test_missing_context_or_pool_rolls_back_paid_and_owner_end_consumers(self):
        for cid in(JACKPOT,ASTRO,AEGIS,SELLER,DRAKE):
            for missing in('context','pool'):
                with self.subTest(cid=cid,missing=missing):
                    end=cid in(SELLER,DRAKE);g=self.game((TEST+'extra',)if end else(cid,),board=(cid,)if end else(),context=None if missing=='context'else CONTEXT,pool=missing!='pool');saved=g.snapshot()
                    with self.assertRaises(ResolutionError):self.play(g,TEST+'extra',self.first(g,cid,'board').id)if end else self.play(g,cid)
                    self.assertEqual(g.snapshot(),saved)

if __name__=='__main__':unittest.main()

