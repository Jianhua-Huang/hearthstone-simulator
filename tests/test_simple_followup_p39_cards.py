"""Original successful cast links and ordinary current-attack branch targets."""
from dataclasses import asdict
import json,random,re,unittest
from unittest.mock import patch
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p39_cards import GROVE,INFLUENCE,TREANT,THORNS,VINES,ROOTS,DEPENDENCIES,CHOICE_ONLY,QUERIES,POOL_ID,load_batch,register_simple_followup_p39_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,Game,IllegalAction,PlayCard,PlayerSetup,Scenario,SelectChoice,SpellSchool,TargetSpec,Zone
from hs_sim.engine.effects import AddToHand,Buff,ChoiceOption,Destroy,InvokeBehavior,RequestChoice,Silence
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.targets import canonical_digest

TEST='p39.test.';YETI='CORE_CS2_182';LOW='CORE_CS2_179';BRIGHT='CORE_EX1_189';TWO='CORE_GVG_085';DORMANT='BT_156';NATURE='EDR_233';OTHER_NATURE='EX1_164';FIRE='CORE_CS2_029'
MEMBERS=(*ROOTS,YETI,LOW,BRIGHT,TWO,NATURE,OTHER_NATURE,FIRE);CONTEXT=GenerationContext('p39-explicit-experiment','experimental');META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    if not all(cid in r.cards for cid in ROOTS+DEPENDENCIES):register_simple_followup_p39_cards(r)
    register_candidate_pool_metadata(r);r.validate();return r

def registry(members=MEMBERS,mode=None,pool=True):
    r=batch_registry()
    for cid in members:
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p39-complete-explicit-fixture-v1',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    def kill_source(c):
        source=next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==GROVE)
        return(Destroy(source,c.source_id),)
    scripts={'nature':lambda c:(),'fire':lambda c:(),'auto':lambda c:(CastSpell(c.player_id,TEST+'nature',c.source_id),),'kill_source':kill_source,'kill':lambda c:(Destroy(c.target_id,c.source_id),),'silence':lambda c:(Silence(c.target_id),),'up':lambda c:(Buff(c.target_id,attack=2,source_id=c.source_id),),'down':lambda c:(Buff(c.target_id,attack=-2,source_id=c.source_id),),'counter':lambda c:(SetSecret(2,'EX1_287'),),'branch':lambda c:(AddToHand(c.player_id,THORNS,c.source_id),),'fail':lambda c:(_ for _ in()).throw(ResolutionError('P39 deliberate original continuation failure'))}
    for name,fn in scripts.items():
        r.register_behavior(TEST+name,fn);r.register_card(CardDefinition(TEST+name,name,CardType.SPELL,on_play=TEST+name,metadata=META,spell_school=SpellSchool.NATURE if name in('nature','kill_source')else SpellSchool.FIRE if name=='fire'else None,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if name in('kill','silence','up','down')else None))
    r.register_card(CardDefinition(TEST+'both','Ordinary Choose Both source',CardType.MINION,attack=5,health=9,choose_both=True,metadata=META))
    if mode:
        def eligible(c):return any(root.request.cause.source.card_id in ROOTS and any(d.outcome=='delivered'and d.entity.entity_id==c.event.target_id for d in root.deliveries)for root in c.state.card_summon_history)
        def watch(c):
            if mode=='fail':return(InvokeBehavior(TEST+'fail',c.source_id,1),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible)
        r.register_card(CardDefinition(TEST+'watch','Original actual entry reaction',CardType.MINION,attack=5,health=9,metadata=META,limited_triggers=(LimitedTriggerSpec('minion_summoned',TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

class SimpleFollowupP39Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),members=MEMBERS,mode=None,pool=True,context=CONTEXT,active=1):
        self.config=(members,mode,pool)
        if mode:board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*6,mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*6,mana=50,max_mana=50,mana_cap=50)),active_player=active,seed=3939,generation_context=context),registry(*self.config))
    def first(self,g,cid,zone='hand',player=1):return next(g.state.entities[i]for i in getattr(g.state.players[player],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None,branch=None,player=1):
        eid=self.first(g,cid,player=player).id;g.apply(PlayCard(player,eid,target,position=len(g.state.players[player].board)if g.registry.card(cid).kind==CardType.MINION else None,branch_id=branch));return eid
    def choose(self,g,key='ok'):g.apply(SelectChoice(1,g.state.pending_choice.id,(key,)))
    def bodies(self,g,source):return[g.state.entities[d.entity.entity_id]for root in g.state.card_summon_history if root.request.cause.source.entity_id==source for d in root.deliveries if d.outcome=='delivered']
    def created(self,g,source):return[g.state.entities[e.target_id]for e in g.events if e.kind=='card_created'and e.source_id==source]
    def actual(self,g,cid):return resolve_candidates(g.registry,CONTEXT,POOL_ID,QUERIES[cid],current_class=g.state.players[1].hero_class,source_card_id=cid,exclude_source_by_rule=True,player_id=1)
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(*self.config));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','pool_id','pool_basis','behavior_id','card_summon_history'):self.assertNotIn('"'+key+'"',public)
        return other

    def test_five_complete_rows_ten_faces_explicit_children_and_shared_metadata_decoder(self):
        d=load_batch();r=batch_registry();self.assertEqual(len(d['cards']+d['dependencies']),5);self.assertEqual(len(d['official_observations']['observations']),10);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete']);raws={x['record']['id']:x['record']for x in d['cards']+d['dependencies']};norm=lambda s:re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']+d['dependencies']:
            raw=row['record'];cid=raw['id'];c=r.card(cid);self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(c.metadata,metadata_from_record(raw));self.assertEqual(c.cost,0 if cid in CHOICE_ONLY else raw['cost']);self.assertEqual(c.choice_only,cid in CHOICE_ONLY);self.assertFalse(c.keywords)
            for o in(o for o in d['official_observations']['observations']if o['card_id']==cid):
                f=o['face'];en=o['locale']=='en_US';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']));self.assertEqual((f['id'],f['manaCost']),(raw['dbf_id'],raw['cost']))
                if cid in ROOTS:self.assertEqual(f['childIds'],[raws[x]['dbf_id']for x in d['explicit_official_children'][cid]])
                else:self.assertEqual(f['parentId'],raws[GROVE if cid==TREANT else INFLUENCE]['dbf_id'])
        self.assertEqual((r.card(GROVE).attack,r.card(GROVE).health),(3,6));self.assertIsNone(r.card(GROVE).deathrattle);self.assertEqual((r.card(TREANT).attack,r.card(TREANT).health),(2,2));self.assertFalse(r.card(TREANT).metadata.collectible);self.assertEqual(raws[TREANT]['tags']['2831'],1);self.assertEqual(r.card(TREANT).metadata.tribes,());self.assertEqual(r.card(INFLUENCE).spell_school,SpellSchool.SHADOW)

    def test_five_new_defs_preserve_old_pool_facts_and_only_token_new_metadata(self):
        with patch('hs_sim.cards.simple_followup_p39_cards.register_simple_followup_p39_cards',lambda r:None):before=build_registry()
        after=batch_registry();self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS+DEPENDENCIES));self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards));self.assertEqual(set(after.pool_cards)-set(before.pool_cards),{TREANT});self.assertTrue(all(before.pool_card(cid)==after.pool_card(cid)for cid in before.pool_cards));self.assertEqual(dict(before.pools),dict(after.pools));self.assertEqual(dict(before.generation_families),dict(after.generation_families))
        for cid in CHOICE_ONLY:self.assertNotIn(cid,after.pool_cards);self.assertIsNone(after.card(cid).on_play)

    def test_default311_uses_existing_current_reviewed_fingerprint_and_no_formal_pool(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT);self.assertFalse(any(p.id==POOL_ID or p.mode=='standard'for p in batch_registry().pools.values()))

    def test_grove_successful_own_nature_spawns_actual_native_treant_after_cast_without_pool(self):
        g=self.game((TEST+'nature',),board=(GROVE,),pool=False,context=None);source=self.first(g,GROVE,'board').id;spell=self.play(g,TEST+'nature');body,=self.bodies(g,source);self.assertEqual((body.card_id,body.attack,body.health),(TREANT,2,2));self.assertTrue(any(a.kind=='deathrattle'for a in body.abilities));cast,=g.state.cast_history;self.assertTrue(cast.completed);self.assertEqual(cast.source_id,spell);self.assertEqual((g.state.card_summon_history[-1].request.cause.source.entity_id,g.state.card_summon_history[-1].request.cause.origin),(source,'card_effect'));self.assertFalse(g.state.battlecry_history);self.portable(g)

    def test_grove_effect_cast_nature_counts_once_beyond_outer_unschooled_hand_spell(self):
        g=self.game((TEST+'auto',),board=(GROVE,),pool=False,context=None);source=self.first(g,GROVE,'board').id;self.play(g,TEST+'auto');self.assertEqual(len(self.bodies(g,source)),1);self.assertEqual({x.card_id for x in g.state.cast_history},{TEST+'auto',TEST+'nature'});self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def test_grove_non_nature_foreign_owner_and_countered_casts_do_not_trigger(self):
        g=self.game((TEST+'fire',),board=(GROVE,),pool=False,context=None);source=self.first(g,GROVE,'board').id;self.play(g,TEST+'fire');self.assertFalse(self.bodies(g,source))
        g=self.game(board=(GROVE,),enemy_hand=(TEST+'nature',),active=2,pool=False,context=None);source=self.first(g,GROVE,'board').id;self.play(g,TEST+'nature',player=2);self.assertFalse(self.bodies(g,source))
        g=self.game((TEST+'counter',TEST+'nature'),board=(GROVE,),pool=False,context=None);source=self.first(g,GROVE,'board').id;self.play(g,TEST+'counter');self.play(g,TEST+'nature');self.assertFalse(self.bodies(g,source));self.assertEqual(g.state.cast_history[-1].failure,'countered')

    def test_grove_dying_during_nature_or_silenced_source_does_not_spawn(self):
        g=self.game((TEST+'kill_source',),board=(GROVE,),pool=False,context=None);source=self.first(g,GROVE,'board').id;self.play(g,TEST+'kill_source');self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertFalse(self.bodies(g,source))
        g=self.game((TEST+'silence',TEST+'nature'),board=(GROVE,),pool=False,context=None);source=self.first(g,GROVE,'board').id;self.play(g,TEST+'silence',source);self.play(g,TEST+'nature');self.assertFalse(self.bodies(g,source))

    def test_grove_multiple_sources_and_fixed_capacity_use_actual_source_id_each(self):
        for count,fill,expected in((2,0,2),(1,6,0)):
            with self.subTest(sources=count,fill=fill):
                g=self.game((TEST+'nature',),board=(GROVE,)*count+(YETI,)*fill,pool=False,context=None);sources=list(g.state.players[1].board[:count]);rng=g._rng.getstate();self.play(g,TEST+'nature');self.assertEqual(sum(len(self.bodies(g,i))for i in sources),expected);self.assertEqual(g._rng.getstate(),rng)

    def test_treant_real_death_gets_anyclass_nature_spell_not_draw_discover_or_summon(self):
        g=self.game((TEST+'kill',),board=(TREANT,),members=(NATURE,FIRE));source=self.first(g,TREANT,'board').id;deck=list(g.state.players[1].deck);self.play(g,TEST+'kill',source);new,=self.created(g,source);self.assertEqual((new.card_id,new.zone),(NATURE,Zone.HAND));self.assertEqual(g.state.players[1].deck,deck);self.assertFalse(g.state.draw_history);self.assertFalse(g.state.card_summon_history);self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_influence_current_attack_targets_both_sides_exclude_high_dormant_heroes_and_hand(self):
        g=self.game((TEST+'up',TEST+'down',INFLUENCE,LOW),board=(LOW,YETI,DORMANT),enemy=(BRIGHT,YETI),pool=False,context=None);low,yeti,dormant=g.state.players[1].board;enemy=g.state.players[2].board[0];source=self.first(g,INFLUENCE).id;self.play(g,TEST+'up',low);self.play(g,TEST+'down',yeti);self.assertEqual(g.state.entities[low].attack,5);self.assertEqual(g.state.entities[yeti].attack,2);self.assertEqual(set(g.legal_targets(source,branch_id=THORNS)),{yeti,enemy});self.assertFalse(g.legal_targets(source,branch_id=VINES));self.play(g,INFLUENCE,yeti,THORNS);self.assertEqual(g.state.entities[yeti].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[dormant].zone,Zone.BOARD);self.assertEqual(g.state.players[1].mana,48);self.portable(g)

    def test_influence_destroy_branch_rejects_missing_high_hero_and_hand_targets_before_payment(self):
        g=self.game((INFLUENCE,LOW),board=(YETI,),pool=False,context=None)
        for target in(None,g.state.players[1].board[0],g.state.players[2].hero_id,self.first(g,LOW).id):
            saved=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,INFLUENCE,target,THORNS)
            self.assertEqual(g.snapshot(),saved)

    def test_influence_untargeted_branch_summons_printed_two_anyclass_without_battlecry(self):
        g=self.game((INFLUENCE,),members=(BRIGHT,),enemy=(YETI,));source=self.play(g,INFLUENCE,branch=VINES);body,=self.bodies(g,source);self.assertEqual(body.card_id,BRIGHT);self.assertFalse(g.state.battlecry_history);self.assertEqual(g.state.players[1].mana,48);self.assertEqual((len(g.state.cast_history),g.state.cast_history[0].branch_id),(1,VINES));self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,5);self.portable(g)

    def test_influence_full_board_or_empty_pool_skips_rng_after_one_payment(self):
        for board,members in(((YETI,)*7,(TWO,)),((),(YETI,))):
            with self.subTest(full=bool(board)):
                g=self.game((INFLUENCE,),board=board,members=members);rng=g._rng.getstate();source=self.play(g,INFLUENCE,branch=VINES);self.assertFalse(self.bodies(g,source));self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.players[1].mana,48)

    def test_influence_combined_destroys_first_freeing_full_board_slot_then_summons_once(self):
        g=self.game((INFLUENCE,),board=(TEST+'both',LOW)+(YETI,)*5,members=(TWO,));victim=g.state.players[1].board[1];source=self.play(g,INFLUENCE,victim,INFLUENCE+':combined');self.assertEqual(g.state.entities[victim].zone,Zone.GRAVEYARD);body,=self.bodies(g,source);self.assertEqual(body.card_id,TWO);self.assertEqual(len(g.state.players[1].board),7);self.assertEqual((g.state.players[1].mana,len(g.state.cast_history),len(g.state.play_history)),(48,1,1));self.portable(g)

    def test_influence_combined_with_no_eligible_target_still_summons_but_requires_target_if_available(self):
        g=self.game((INFLUENCE,),board=(TEST+'both',),enemy=(YETI,),members=(TWO,));source=self.play(g,INFLUENCE,branch=INFLUENCE+':combined');self.assertEqual(len(self.bodies(g,source)),1);self.assertFalse(g.state.death_history)
        g=self.game((INFLUENCE,),board=(TEST+'both',),enemy=(LOW,),members=(TWO,));saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,INFLUENCE,branch=INFLUENCE+':combined')
        self.assertEqual(g.snapshot(),saved)

    def test_choice_only_branch_cannot_be_created_as_physical_hand_card(self):
        g=self.game((TEST+'branch',));saved=g.snapshot()
        with self.assertRaises((ResolutionError,ValueError)):self.play(g,TEST+'branch')
        self.assertEqual(g.snapshot(),saved)

    def test_first_fixed_or_pool_entry_wait_restore_clone_independent_replay_bad_resume(self):
        for cid in ROOTS:
            with self.subTest(cid=cid):
                g=self.game((TEST+'nature',),board=(GROVE,),mode='wait')if cid==GROVE else self.game((INFLUENCE,),members=(TWO,),mode='wait');source=self.first(g,GROVE,'board').id if cid==GROVE else self.first(g,INFLUENCE).id;self.play(g,TEST+'nature')if cid==GROVE else self.play(g,INFLUENCE,branch=VINES);self.assertEqual(len(self.bodies(g,source)),1);other=self.portable(g);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.choose(g,'bad')
                self.assertEqual(g.snapshot(),saved)
                for game in(g,other):self.choose(game)
                self.assertEqual(g.snapshot(),other.snapshot());self.portable(g)

    def test_late_spawn_failure_rolls_back_nature_cast_or_combined_destruction_and_payment(self):
        g=self.game((TEST+'nature',),board=(GROVE,),mode='fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,TEST+'nature')
        self.assertEqual(g.snapshot(),saved)
        g=self.game((INFLUENCE,),board=(TEST+'both',),enemy=(LOW,),members=(TWO,),mode='fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,INFLUENCE,g.state.players[2].board[0],INFLUENCE+':combined')
        self.assertEqual(g.snapshot(),saved)

    def test_unknown_nature_and_two_cost_eligible_candidates_fail_before_rng_and_roll_back(self):
        for cid,unknown in((TREANT,'CATA_567'),(INFLUENCE,'CAP_104')):
            with self.subTest(cid=cid):
                g=self.game((TEST+'kill',)if cid==TREANT else(INFLUENCE,),board=(TREANT,)if cid==TREANT else(),members=(*MEMBERS,unknown));saved=g.snapshot();self.assertNotIn(unknown,g.registry.cards)
                with patch.object(random.Random,'randrange',side_effect=AssertionError('Unknown sampled'))as calls:
                    with self.assertRaises(ResolutionError):self.play(g,TEST+'kill',self.first(g,TREANT,'board').id)if cid==TREANT else self.play(g,INFLUENCE,branch=VINES)
                    calls.assert_not_called()
                self.assertEqual(g.snapshot(),saved)

    def test_only_generated_requests_need_context_pool_fixed_trigger_and_destroy_branch_do_not(self):
        for cid in(TREANT,INFLUENCE):
            for missing in('context','pool'):
                with self.subTest(cid=cid,missing=missing):
                    g=self.game((TEST+'kill',)if cid==TREANT else(INFLUENCE,),board=(TREANT,)if cid==TREANT else(),context=None if missing=='context'else CONTEXT,pool=missing!='pool');saved=g.snapshot()
                    with self.assertRaises(ResolutionError):self.play(g,TEST+'kill',self.first(g,TREANT,'board').id)if cid==TREANT else self.play(g,INFLUENCE,branch=VINES)
                    self.assertEqual(g.snapshot(),saved)

if __name__=='__main__':unittest.main()
