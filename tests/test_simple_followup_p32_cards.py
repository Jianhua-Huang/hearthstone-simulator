"""Eight real card entries; explicit experimental inventories, no pool fallback."""
from dataclasses import asdict,replace
import json,random,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p32_cards import IRON,SILVER,HORN,BLOOD,BIOME,REGROWTH,DETHRONE,GUARD,ROOTS,DEPENDENCIES,IDENTITIES,QUERIES,POOL_ID,load_batch,register_simple_followup_p32_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,PaymentType,PlayCard,PlayerSetup,Scenario,SelectChoice,UseLocation,Zone
from hs_sim.engine.effects import ChoiceOption,Damage,InvokeBehavior,RequestChoice,Summon
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import ChoicePurpose,LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates,sample_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.targets import canonical_digest
TEST='p32.test.';YETI='CORE_CS2_182';TWO='CORE_GVG_085';FOUR='CORE_CS2_179';SIX='CORE_BAR_310';EIGHT='CORE_NEW1_010';NATURE='CS2_009';NATURE4='CORE_LOOT_309';MAGE='CS2_029';ONE='JAIL_460'
MEMBERS=(*ROOTS,YETI,TWO,FOUR,SIX,EIGHT,NATURE,NATURE4,MAGE,ONE);CONTEXT=GenerationContext('p32-explicit-experiment','experimental');META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    if not all(cid in r.cards for cid in ROOTS):register_simple_followup_p32_cards(r)
    register_candidate_pool_metadata(r);r.validate();return r

def registry(members=MEMBERS,mode=None,pool=True):
    r=batch_registry()
    for cid in members:
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p32-complete-explicit-fixture-v1',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    scripts={'noop':lambda c:(), 'hurt':lambda c:(Damage(c.state.players[1].hero_id,27,c.source_id),),
        'auto':lambda c:(CastSpell(1,BLOOD,c.source_id,choices='player'),),'summon':lambda c:(Summon(1,REGROWTH),),
        'fail':lambda c:(_ for _ in()).throw(ResolutionError('P32 deliberate continuation failure'))}
    for name,body in scripts.items():
        r.register_behavior(TEST+name,body);r.register_card(CardDefinition(TEST+name,name,CardType.SPELL,on_play=TEST+name,metadata=META))
    if mode:
        def eligible(c):
            if mode=='fail_hand':return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==HORN
            expected=GUARD if mode=='wait'else IRON
            return c.event.player_id==1 and any(root.request.cause.source.card_id==expected and any(d.outcome=='delivered'and d.entity.entity_id==c.event.target_id for d in root.deliveries)for root in c.state.card_summon_history)
        def watch(c):
            if mode.startswith('fail'):return(InvokeBehavior(TEST+'fail',c.source_id,1),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible)
        r.register_card(CardDefinition(TEST+'watch','Native source arrival reaction',CardType.MINION,health=9,metadata=META,
            limited_triggers=(LimitedTriggerSpec('card_added_to_hand'if mode=='fail_hand'else'minion_summoned',TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

class SimpleFollowupP32Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),members=MEMBERS,mode=None,pool=True,context=CONTEXT,hero='HERO_08'):
        self.members=members;self.mode=mode;self.pool=pool
        if mode:board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8)),seed=3232,generation_context=context),registry(members,mode,pool))
    def first(self,g,cid,p=1,zone='hand'):return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.first(g,cid).id;g.apply(PlayCard(1,eid,target,len(g.state.players[1].board)if g.registry.card(cid).kind in(CardType.MINION,CardType.LOCATION)else None));return eid
    def choose(self,g,card=None,key=None):
        q=g.state.pending_choice;selected=key if key is not None else next(o.id for o in q.options if card is None or o.card_id==card);g.apply(SelectChoice(q.player_id,q.id,(selected,)))
    def created(self,g,source):return[e for e in g.events if e.kind=='card_created'and e.source_id==source]
    def summons(self,g,source):
        ids={d.entity.entity_id for root in g.state.card_summon_history if root.request.cause.source.entity_id==source for d in root.deliveries if d.outcome=='delivered'}
        return[e for e in g.events if e.kind=='minion_summoned'and e.target_id in ids]
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(self.members,self.mode,self.pool));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(self.members,self.mode,self.pool)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','pool_id','behavior_id','rewind_session','candidate_root_ids','pool_summon_history'):self.assertNotIn('"'+key+'"',public)
        return other
    def actual(self,g,cid,key=None):return resolve_candidates(g.registry,CONTEXT,POOL_ID,QUERIES[key or cid],current_class=g.state.players[1].hero_class,source_card_id=cid,exclude_source_by_rule=True,player_id=1)

    def test_eleven_complete_rows_sixteen_faces_full_metadata_and_actual_entry_kinds(self):
        d=load_batch();r=batch_registry();self.assertEqual(len(d['cards']+d['skipped']+d['evidence_only']),11);self.assertEqual(len(d['official_observations']['observations']),16);self.assertTrue(d['required_generation_context']);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']:
            raw=row['record'];cid=raw['id'];c=r.card(cid);self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(c.metadata,replace(metadata_from_record(raw),deck_identity=IDENTITIES[cid]));self.assertEqual(c.kind,CardType(raw['type'].lower()));self.assertEqual(c.cost,raw['cost'])
            for o in(o for o in d['official_observations']['observations']if o['card_id']==cid):
                f=o['face'];en=o['locale'].lower().replace('_','-')=='en-us';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']));self.assertEqual((f['id'],f['manaCost']),(raw['dbf_id'],c.cost))
            self.assertEqual(c.keywords,(Keyword.REWIND,)if cid==REGROWTH else(Keyword.COMBO,)if cid==DETHRONE else())
        self.assertEqual(r.card(BLOOD).cost_payment,PaymentType.HEALTH);self.assertEqual(r.card(BLOOD).metadata.runes.blood,1);self.assertEqual(d['skipped'][0]['record']['type'],'LOCATION');self.assertEqual(d['skipped'][0]['record']['health'],2);self.assertEqual((r.card(REGROWTH).attack,r.card(REGROWTH).health),(3,5));self.assertIsNotNone(r.card(REGROWTH).rewind);self.assertIsNone(r.card(DETHRONE).combo)

    def test_seven_new_defs_old_definitions_catalog_aliases_and_families_preserved(self):
        with patch('hs_sim.cards.simple_followup_p32_cards.register_simple_followup_p32_cards',lambda r:None):before=build_registry()
        after=batch_registry();self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS));self.assertFalse(DEPENDENCIES);self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards));self.assertEqual(dict(before.pools),dict(after.pools));self.assertEqual(dict(before.generation_families),dict(after.generation_families));self.assertEqual(set(before.pool_cards),set(after.pool_cards))
        for cid,row in before.pool_cards.items():self.assertEqual(replace(row,metadata=replace(row.metadata,deck_identity=IDENTITIES[cid]))if cid in ROOTS else row,after.pool_card(cid))
        for cid in('WON_337','KAR_091','KAR_077'):self.assertEqual(cid in before.cards,cid in after.cards)
        self.assertFalse(any(p.id==POOL_ID or p.mode=='standard'for p in after.pools.values()))

    def test_default311_complete_fingerprint_unchanged(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')

    def test_guard_exact_separate_cost_and_taunt_queries(self):
        g=self.game(members=(SIX,FOUR,TWO,YETI,EIGHT));self.assertEqual([{m.card_id for m in self.actual(g,GUARD,GUARD+'.'+str(n))}for n in(6,4,2)],[{SIX},{FOUR},{TWO}]);self.assertEqual(QUERIES[HORN].class_mode,'current');self.assertEqual(QUERIES[REGROWTH].class_mode,'any');self.assertEqual(QUERIES[BIOME].kinds,(CardType.MINION,))

    def test_iron_paid_four_gains_armor_then_attributed_four_cost_summon(self):
        g=self.game((IRON,),members=(YETI,));source=self.play(g,IRON);hero=g.state.entities[g.state.players[1].hero_id];self.assertEqual((hero.armor,g.state.players[1].mana),(4,46));event,=self.summons(g,source);self.assertEqual(g.state.entities[event.target_id].card_id,YETI);cause=g.state.card_summon_history[0].request.cause;self.assertEqual((cause.source.entity_id,cause.cast_card_id),(source,IRON));self.portable(g)

    def test_iron_full_board_keeps_armor_and_skips_summon_rng(self):
        g=self.game((IRON,),board=(YETI,)*7,members=(YETI,));before=g._rng.getstate();source=self.play(g,IRON);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,4);self.assertFalse(self.summons(g,source));self.assertEqual(g._rng.getstate(),before)

    def test_silver_buffs_enemy_original_minion_then_summons_two_cost(self):
        g=self.game((SILVER,),enemy=(YETI,),members=(TWO,));target=self.first(g,YETI,2,'board').id;source=self.play(g,SILVER,target);self.assertEqual((g.state.entities[target].attack,g.state.entities[target].max_health),(6,7));event,=self.summons(g,source);self.assertEqual(g.state.entities[event.target_id].card_id,TWO);self.assertEqual(g.state.players[1].mana,47)

    def test_silver_and_dethrone_require_minion_not_hero_before_payment(self):
        for cid in(SILVER,DETHRONE):
            for target in(None,1):
                with self.subTest(cid=cid,target=target):
                    g=self.game((cid,));saved=g.snapshot()
                    with self.assertRaises(IllegalAction):self.play(g,cid,None if target is None else g.state.players[2].hero_id)
                    self.assertEqual(g.snapshot(),saved)

    def test_horn_selected_permanent_discount_is_flat_minus_two_with_zero_floor(self):
        for card,expected in((NATURE,0),(NATURE4,2)):
            with self.subTest(card=card):
                g=self.game((HORN,card),members=(card,),hero='HERO_06');old=self.first(g,card).id;source=self.play(g,HORN);self.choose(g);event,=self.created(g,source);new=g.state.entities[event.target_id];self.assertNotEqual(new.id,old);self.assertEqual(g.quote_cost(new.id).amount,expected);self.assertEqual(g.quote_cost(old).amount,g.registry.card(card).cost);self.assertTrue(any(e.cost==-2 and e.set_cost is None and e.expires_turn is None for e in new.enchantments));g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(g.quote_cost(new.id).amount,expected)

    def test_horn_source_only_pool_is_empty_without_rng(self):
        g=self.game((HORN,),members=(HORN,),hero='HERO_06');before=g._rng.getstate()
        with patch.object(random.Random,'randrange',side_effect=AssertionError('Self-only Horn consumed RNG'))as calls:self.play(g,HORN);calls.assert_not_called()
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g._rng.getstate(),before);self.assertEqual(g.state.players[1].mana,48)

    def test_blood_native_health_quote_payment_one_blood_rune_and_no_mana_charge(self):
        g=self.game((BLOOD,),members=(MAGE,));eid=self.first(g,BLOOD).id;quote=g.quote_cost(eid);self.assertEqual((quote.amount,quote.payment),(3,PaymentType.HEALTH));self.play(g,BLOOD);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,27);self.assertEqual(g.state.players[1].mana,50);self.assertTrue(any(e.kind=='health_spent'and e.amount==3 for e in g.events));self.choose(g);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,27)

    def test_blood_cannot_spend_last_health_and_fails_before_effect(self):
        g=self.game((TEST+'hurt',BLOOD),members=(MAGE,));self.play(g,TEST+'hurt');self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,3);saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,BLOOD)
        self.assertEqual(g.snapshot(),saved)

    def test_generated_blood_cast_does_not_pay_printed_health_cost(self):
        g=self.game((TEST+'auto',),members=(MAGE,));self.play(g,TEST+'auto');self.assertIsNotNone(g.state.pending_choice);self.assertEqual((g.state.entities[g.state.players[1].hero_id].health,g.state.players[1].mana),(30,50));self.choose(g);self.assertFalse([e for e in g.events if e.kind=='health_spent'])

    def test_regrowth_native_rewind_battlecry_two_unpaid_nature_casts_then_keep(self):
        g=self.game((REGROWTH,),members=(NATURE,));source=self.play(g,REGROWTH);self.assertEqual([c.card_id for c in g.state.cast_history],[NATURE,NATURE]);self.assertEqual(g.state.players[1].mana,44);self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.REWIND);self.assertEqual(len(g.state.battlecry_history),1);self.choose(g,key='keep');self.assertEqual(g.state.players[1].board,[source]);self.assertEqual(g.state.players[1].mana,44)

    def test_regrowth_retry_keeps_only_two_committed_casts_and_one_payment(self):
        g=self.game((REGROWTH,),members=(NATURE,));source=self.play(g,REGROWTH);self.choose(g,key='retry');self.assertIsNone(g.state.pending_choice);self.assertEqual([c.card_id for c in g.state.cast_history],[NATURE,NATURE]);self.assertEqual(g.state.players[1].mana,44);self.assertEqual(g.state.players[1].board,[source]);self.portable(g)

    def test_regrowth_natural_summon_has_no_battlecry_or_rewind_without_pool(self):
        g=self.game((TEST+'summon',),pool=False,context=None);self.play(g,TEST+'summon');self.assertIsNone(g.state.pending_choice);self.assertFalse(g.state.battlecry_history);self.assertEqual(len(g.state.cast_history),1)

    def test_dethrone_noncombo_destroys_only_and_needs_no_pool(self):
        g=self.game((DETHRONE,),enemy=(YETI,),pool=False,context=None);target=self.first(g,YETI,2,'board').id;source=self.play(g,DETHRONE,target);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertFalse(self.summons(g,source));self.assertFalse(g.state.cast_history[-1].combo);self.assertEqual(g.state.players[1].mana,43)

    def test_dethrone_native_spell_combo_destroys_then_summons_with_single_payment(self):
        g=self.game((TEST+'noop',DETHRONE),board=(YETI,),members=(EIGHT,));self.play(g,TEST+'noop');target=self.first(g,YETI,zone='board').id;source=self.play(g,DETHRONE,target);self.assertTrue(g.state.cast_history[-1].combo);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);event,=self.summons(g,source);self.assertEqual(g.state.entities[event.target_id].card_id,EIGHT);self.assertEqual(g.state.players[1].mana,43);self.assertEqual(len(g.state.play_history),2)

    def test_guard_three_separate_six_four_two_taunt_requests_in_source_order(self):
        g=self.game((GUARD,),members=(SIX,FOUR,TWO));source=self.play(g,GUARD);self.assertEqual([g.state.entities[e.target_id].card_id for e in self.summons(g,source)],[SIX,FOUR,TWO]);self.assertEqual(len(g.state.card_summon_history),3);self.assertTrue(all(r.request.cause.source.entity_id==source for r in g.state.card_summon_history));self.assertEqual(g.state.players[1].mana,43)

    def test_guard_capacity_rechecked_per_group_and_last_full_group_skips_rng(self):
        g=self.game((GUARD,),board=(YETI,)*5,members=(SIX,FOUR,TWO));rng=random.Random();rng.setstate(g._rng.getstate())
        for n in(6,4):sample_candidates(rng,self.actual(g,GUARD,GUARD+'.'+str(n)),1,replacement=True)
        source=self.play(g,GUARD);self.assertEqual([g.state.entities[e.target_id].card_id for e in self.summons(g,source)],[SIX,FOUR]);self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(g._rng.getstate(),rng.getstate());self.assertEqual(g.state.card_summon_history[-1].status,'skipped')

    def test_missing_context_rolls_back_armor_buff_health_payment_and_rewind(self):
        for cid in(IRON,SILVER,BLOOD,REGROWTH):
            with self.subTest(cid=cid):
                g=self.game((cid,)if cid!=BIOME else(),board=(BIOME,)if cid==BIOME else(YETI,),context=None);saved=g.snapshot()
                with self.assertRaises(ResolutionError):
                    if cid==BIOME:g.apply(UseLocation(1,self.first(g,BIOME,zone='board').id))
                    else:self.play(g,cid,self.first(g,YETI,zone='board').id if cid==SILVER else None)
                self.assertEqual(g.snapshot(),saved)

    def test_real_unknown_candidates_fail_before_each_first_request_rng(self):
        for cid,unknown,hero in((IRON,'CAP_005','HERO_08'),(HORN,'EDR_060','HERO_06'),(BLOOD,'DINO_414','HERO_08'),(REGROWTH,'EDR_060','HERO_08')):
            with self.subTest(cid=cid):
                g=self.game((cid,)if cid!=BIOME else(),board=(BIOME,)if cid==BIOME else(),members=(*MEMBERS,unknown),hero=hero);saved=g.snapshot();self.assertNotIn(unknown,g.registry.cards)
                with patch.object(random.Random,'randrange',side_effect=AssertionError('Unknown before request RNG'))as calls:
                    with self.assertRaises(ResolutionError):
                        if cid==BIOME:g.apply(UseLocation(1,self.first(g,BIOME,zone='board').id))
                        else:self.play(g,cid)
                    calls.assert_not_called()
                self.assertEqual(g.snapshot(),saved)

    def test_guard_unknown_second_group_rolls_back_first_summon_and_rng(self):
        g=self.game((GUARD,),members=(SIX,'JAIL_311',TWO));saved=g.snapshot();original=random.Random.randrange
        with patch.object(random.Random,'randrange',autospec=True,side_effect=original)as calls:
            with self.assertRaises(ResolutionError):self.play(g,GUARD)
            self.assertTrue(calls.called)
        self.assertEqual(g.snapshot(),saved)

    def test_guard_first_summon_wait_restore_clone_replay_bad_resume_then_later_groups(self):
        g=self.game((GUARD,),members=(SIX,FOUR,TWO),mode='wait');source=self.play(g,GUARD);self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(self.summons(g,source)),1);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,key='bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g,key='ok');self.choose(other,key='ok');self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual([g.state.entities[e.target_id].card_id for e in self.summons(g,source)],[SIX,FOUR,TWO]);self.portable(g)

    def test_late_iron_arrival_failure_rolls_back_armor_summon_and_payment(self):
        g=self.game((IRON,),members=(YETI,),mode='fail_board');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,IRON)
        self.assertEqual(g.snapshot(),saved)

    def test_late_horn_selection_failure_retains_committed_offer_and_rng(self):
        g=self.game((HORN,),members=(NATURE,),hero='HERO_06',mode='fail_hand');self.play(g,HORN);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),saved)

if __name__=='__main__':unittest.main()
