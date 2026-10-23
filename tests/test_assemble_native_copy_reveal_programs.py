"""Actual live copy delivery, hidden pair and captured physical reveal programs."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import json,unittest

from hs_sim.cards import assemble_native_copy_reveal_programs as cards
from hs_sim.cards.constructed import build_registry
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.native_assemble_entry_cards import POOL_ID
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,Game,Keyword,PlayCard,
    PlayerSetup,Scenario,SelectChoice,SnapshotError,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.assemble_offers import recipe_options
from hs_sim.engine.deck_reveals import EVENT,RevealRandomDeckCard,deck_reveal_result
from hs_sim.engine.effects import ChoiceOption,Damage,Draw,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CostSpec,LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference,ModifyStoredCost
from hs_sim.targets import TargetValidationError,canonical_digest
from tools.card_batch import check_face,sha

COPY_SOURCE,REVEAL=cards.SOURCES
RUST,PHOENIX,HIGH,LOW,NECRO,FOOT,TROGG,DRAKE=cards.DEPENDENCIES
P='k449.'
N,PING,BOOST,CHEAP,RAISE,WATCH,FAIL=(P+x for x in('n','ping','boost','cheap','raise','watch','fail'))
COIN='GAME_005';META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
CTX=GenerationContext('k449-complete-reviewed-copy-reveal-domains','experimental')


def recipe(a,b=None,half='bottom'):return AssembleRecipe(a,b or a,half).card_id


def nodes(value,name):
    if isinstance(value,dict):
        if str(value.get('type','')).endswith('.'+name):yield value
        for child in value.values():yield from nodes(child,name)
    elif isinstance(value,list):
        for child in value:yield from nodes(child,name)


def rehash(s):
    s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')});return s


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=build_registry();r._version+='.k449.'+mode
    r.register_card(CardDefinition(N,N,CardType.MINION,attack=1,health=20,metadata=META))
    def fail(c):raise ResolutionError('K449 deliberate late selected program failure')
    r.register_behavior(FAIL,fail)
    def price(c,delta):
        entity=c.state.entities[c.state.players[1].deck[0]]
        return(ModifyStoredCost(CardReference.capture(entity),CostSpec(delta=delta),c.source_id),)
    scripts={PING:lambda c:(Damage(c.target_id,1,c.source_id),),
        BOOST:lambda c:(BuffStoredCard(CardReference.capture(c.state.entities[c.target_id]),2,3,c.source_id),),
        CHEAP:lambda c:price(c,-3),RAISE:lambda c:price(c,1)}
    for cid,fn in scripts.items():
        r.register_behavior(cid,fn);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if cid==PING else
                TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,),relation='friendly')if cid==BOOST else None))
    if mode in('wait','reprice','copy_wait'):
        def watch(c):
            if mode=='copy_wait'and c.state.entities[c.event.target_id].origin_entity_id is None:return ()
            if mode=='reprice':
                result=deck_reveal_result(c.event)
                return ()if result.card is None else(ModifyStoredCost(result.card.card,CostSpec(set_to=0),c.source_id),)
            extra=()if mode=='copy_wait'else(Draw(1,1,c.source_id),)
            return(RequestChoice(1,(ChoiceOption('go','Continue',extra),
                ChoiceOption('bad','Fail',(InvokeBehavior(FAIL,c.source_id,1),))),c.source_id),)
        r.register_behavior(WATCH,watch)
        kw=dict(triggers=(TriggerSpec('minion_summoned',WATCH),))if mode=='copy_wait'else dict(limited_triggers=(LimitedTriggerSpec(EVENT,WATCH),))
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,**kw))
    original=r.behavior(r.card(RUST).battlecry)
    def audited(c):
        if c.event is not None and c.event.kind==EVENT:
            if c.battlecry is None or c.target_id!=c.battlecry.target_id:raise ResolutionError('Reveal body lost its original root or target')
            if mode=='suffix_fail':raise ResolutionError('K449 actual selected suffix failure')
        return original(c)
    r._behaviors[r.card(RUST).battlecry]=audited
    if mode=='changed':r._behaviors[r.card(REVEAL).battlecry]=lambda c:(RevealRandomDeckCard(c.player_id,CardType.MINION,c.source_id,'cards.spire_guard.original_reveal_reward'),)
    domains={'copy_offer':(COPY_SOURCE,TROGG,DRAKE),'reveal_offer':(REVEAL,TROGG,DRAKE)}
    if mode in domains:r.register_pool(PoolDefinition(POOL_ID,'k449-three-complete-eligible-fragments',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in domains[mode]),complete=True))
    r.validate();return r


class AssembleNativeCopyRevealTests(unittest.TestCase):
    def game(self,hand=(),board=(),deck=(HIGH,),enemy=(),mode='normal',weapon=False,corpses=0):
        if mode in('wait','reprice','copy_wait'):board=board+(WATCH,)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=30,max_mana=30,mana_cap=40,corpses=corpses),
            PlayerSetup('HERO_08',board=enemy,deck=(COIN,)*16,weapon_card_id='CS2_091'if weapon else None)),seed=6,generation_context=CTX),fixture(mode))
    def ids(self,g,cid,p=1,zone='board'):return[i for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid]
    def play(self,g,cid,target=None):
        source=self.ids(g,cid,zone='hand')[0];g.apply(PlayCard(1,source,target));return source
    def choose(self,g,key='go'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def pairs(self,g):return[e for e in g.events if e.kind=='hidden_damage_pair_marked']
    def portable(self,g,mode='normal'):
        saved=json.loads(json.dumps(g.snapshot()));reader=fixture(mode,'reader');self.assertIsNot(reader,g.registry)
        other=Game.from_snapshot(saved,reader);self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);self.assertEqual(g.snapshot(),saved)
        for p in(1,2):
            text=json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for key in('selected_index','AssembleRevealContinuation','resolution_frame','rng_state'):
                self.assertNotIn('"'+key+'"',text)
            self.assertNotIn('cards.hand_mirror.fragile',text)
        return other

    def test_a_ten_complete_rows_eighteen_primary_faces_and_exact_original_self_definitions(self):
        d=cards.load_batch();r=fixture();rows={x['record']['id']:x for x in d['existing_dependencies']};self.assertEqual((len(rows),len(d['official_observations'])),(10,18))
        for o in d['official_observations']:
            self.assertEqual(sha(o['response_file']),o['response_sha256']);check_face(rows[o['card_id']]['record'],o['face'],o['locale'],d['display_normalizations'].get(o['card_id']))
        for cid,row in rows.items():self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
        for cid in cards.SOURCES:
            new=asdict(r.card(recipe(cid)));new['id']=cid;self.assertEqual(new,asdict(r.card(cid)));self.assertEqual(recipe_options(r,cid,cid),())

    def test_b_raw_self_copy_keep_two_actual_bodies_one_battlecry_and_one_private_pair(self):
        for cid in(COPY_SOURCE,recipe(COPY_SOURCE)):
            g=self.game((cid,));self.play(g,cid);self.assertEqual(len(self.ids(g,cid)),2);self.assertEqual(len(g.state.battlecry_history),1)
            self.assertEqual(len(self.pairs(g)),1)
        self.portable(g)

    def test_c_current_hand_stats_and_actual_fragile_body_survive_alias_copy_material(self):
        cid=recipe(COPY_SOURCE);g=self.game((cid,BOOST,PING,PING));source=self.ids(g,cid,zone='hand')[0];self.play(g,BOOST,source);self.play(g,cid)
        bodies=self.ids(g,cid);self.assertEqual([(g.state.entities[i].attack,g.state.entities[i].max_health)for i in bodies],[(g.registry.card(COPY_SOURCE).attack+2,g.registry.card(COPY_SOURCE).health+3)]*2)
        fragile=next(i for i in bodies if any(a.behavior_id=='cards.hand_mirror.fragile'for a in g.state.entities[i].abilities));real=next(i for i in bodies if i!=fragile)
        self.play(g,PING,fragile);self.assertEqual(g.state.entities[fragile].zone,Zone.GRAVEYARD);self.play(g,PING,real);self.assertIn(real,g.state.players[1].board);self.portable(g)

    def test_d_replacing_copy_suffix_drops_entire_copy_and_pair_program(self):
        cid=recipe(COPY_SOURCE,RUST);g=self.game((cid,),weapon=True);self.play(g,cid)
        self.assertEqual(len(self.ids(g,cid)),1);self.assertIsNone(g.state.players[2].weapon_id);self.assertEqual(self.pairs(g),[])

    def test_e_borrowed_copy_body_uses_actual_primary_stats_and_original_copy_success(self):
        cid=recipe(RUST,COPY_SOURCE);g=self.game((cid,),weapon=True);self.play(g,cid)
        self.assertEqual(len(self.ids(g,cid)),2);self.assertEqual({g.state.entities[i].max_health for i in self.ids(g,cid)},{g.registry.card(RUST).health})
        self.assertIsNotNone(g.state.players[2].weapon_id);self.assertEqual(len(self.pairs(g)),1);self.portable(g)

    def test_f_full_board_copy_failure_never_marks_pair_or_uses_hidden_pair_rng(self):
        cid=recipe(COPY_SOURCE);g=self.game((cid,),board=(N,)*6);before=g._rng.getstate();self.play(g,cid)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(self.pairs(g),[]);self.assertEqual(g._rng.getstate(),before)

    def test_g_actual_copy_delivery_wait_restores_before_one_original_secret_mark(self):
        cid=recipe(RUST,COPY_SOURCE);g=self.game((cid,),mode='copy_wait');self.play(g,cid);self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.pairs(g),[])
        other=self.portable(g,'copy_wait');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.pairs(g)),1)

    def test_h_dead_copy_is_explicit_pending_dependency_not_a_silent_white_body(self):
        r=fixture();self.assertEqual(r.assemble_templates[COPY_SOURCE].suffix.pending_timings,('deathrattle',))
        with self.assertRaisesRegex(ValueError,'deathrattle'):r.card(recipe('JAIL_328',COPY_SOURCE))
        with self.assertRaisesRegex(ValueError,'deathrattle'):recipe_options(r,'JAIL_328',COPY_SOURCE)

    def test_i_raw_self_reveal_only_actual_spells_with_high_low_and_empty_domains(self):
        for cid in(REVEAL,recipe(REVEAL)):
            for deck,yes in(((HIGH,),True),((LOW,),False),((N,),False),((),False)):
                g=self.game((cid,),deck=deck,enemy=(N,));before=list(g.state.players[1].deck);self.play(g,cid)
                self.assertEqual(g.state.entities[self.ids(g,N,2)[0]].health,15 if yes else 20);self.assertEqual(g.state.players[1].deck,before);self.assertEqual(g.state.draw_history,[])

    def test_j_local_deck_cost_not_printed_cost_controls_native_threshold(self):
        for spell,change,yes in((HIGH,CHEAP,False),(LOW,RAISE,True)):
            cid=recipe(REVEAL,RUST);g=self.game((cid,change),deck=(spell,),weapon=True);self.play(g,change);self.play(g,cid)
            self.assertEqual(g.state.players[2].weapon_id is None,yes);self.assertEqual(g.state.damage_history,[])

    def test_k_replacing_reveal_prefix_keeps_only_free_original_five_damage_reward(self):
        cid=recipe(REVEAL,RUST,'top');g=self.game((cid,),deck=(),enemy=(N,));self.play(g,cid)
        self.assertEqual(g.state.entities[self.ids(g,N,2)[0]].health,15);self.assertFalse(any(e.kind==EVENT for e in g.events))

    def test_l_reprice_reaction_after_reveal_cannot_change_captured_original_cost(self):
        cid=recipe(REVEAL,RUST);g=self.game((cid,),mode='reprice',weapon=True);self.play(g,cid)
        self.assertIsNone(g.state.players[2].weapon_id);self.assertEqual(next(e.amount for e in g.events if e.kind==EVENT),7);self.portable(g,'reprice')

    def test_m_reveal_wait_then_original_card_draw_uses_saved_result_once(self):
        cid=recipe(REVEAL,RUST);g=self.game((cid,),mode='wait',weapon=True);physical=g.state.players[1].deck[0];self.play(g,cid);self.assertIsNotNone(g.state.players[2].weapon_id)
        other=self.portable(g,'wait');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertIn(physical,g.state.players[1].hand);self.assertIsNone(g.state.players[2].weapon_id)
        self.assertEqual(sum(e.kind==EVENT for e in g.events),1)

    def test_n_selected_character_target_stays_original_after_targetless_reveal(self):
        cid=recipe(REVEAL,PHOENIX);g=self.game((cid,));hero=g.state.players[2].hero_id;self.play(g,cid,hero)
        self.assertEqual(g.state.entities[hero].health,27);self.portable(g)

    def test_o_selected_necromancer_body_keeps_original_battlecry_and_one_actual_payment(self):
        cid=recipe(REVEAL,NECRO);g=self.game((cid,),corpses=1);self.play(g,cid)
        self.assertEqual(len(self.ids(g,FOOT)),1);self.assertEqual(len(g.state.battlecry_history),1);self.assertEqual(len(g.state.corpse_spend_history),1);self.portable(g)

    def test_p_rehashed_callback_cannot_borrow_cursor_player_body_or_inconsistent_cost(self):
        cid=recipe(REVEAL,RUST);g=self.game((cid,),mode='wait');self.play(g,cid);saved=g.snapshot();self.assertTrue(list(nodes(saved,'ResolveAssembledRevealResult')))
        for change in('cursor','player','body','cost'):
            bad=deepcopy(saved);callback=next(nodes(bad,'ResolveAssembledRevealResult'))['fields'];m=callback['continuation']['fields']
            if change=='cursor':m['events_before']=999
            elif change=='player':m['accepted']['fields']['player_id']=2
            elif change=='body':m['behavior_id']=cards.PREFIX+'damage_reward'
            else:callback['context']['fields']['event']['event']['amount']+=1
            with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture('wait','reader'))

    def test_q_true_low_cost_copy_offer_borrows_taunt_prefix_and_copies_actual_low_primary(self):
        cid=recipe(COPY_SOURCE,DRAKE,'top');g=self.game((MISMATCH,),mode='copy_offer');self.play(g,MISMATCH);q=g.state.pending_choice
        self.assertIn(cid,[o.card_id for o in q.options]);self.choose(g,next(o.id for o in q.options if o.card_id==cid));self.play(g,cid)
        self.assertEqual(len(self.ids(g,cid)),2)
        for i in self.ids(g,cid):self.assertIn(Keyword.TAUNT,g.state.entities[i].keywords);self.assertEqual(g.state.entities[i].max_health,g.registry.card(COPY_SOURCE).health)
        self.portable(g,'copy_offer')

    def test_r_true_low_cost_reveal_offer_gates_drake_body_without_original_random_five(self):
        cid=recipe(REVEAL,DRAKE);g=self.game((MISMATCH,),enemy=(N,N),mode='reveal_offer');self.play(g,MISMATCH);q=g.state.pending_choice
        self.assertIn(cid,[o.card_id for o in q.options]);self.choose(g,next(o.id for o in q.options if o.card_id==cid));self.play(g,cid)
        self.assertEqual([g.state.entities[i].health for i in self.ids(g,N,2)],[18,18]);self.portable(g,'reveal_offer')

    def test_s_reveal_source_is_readonly_unique_frozen_and_complete_original_pins_strict(self):
        r=fixture.__wrapped__();source=r.assemble_reveal_sources[REVEAL]
        with self.assertRaises(TypeError):r.assemble_reveal_sources[REVEAL]=source
        with self.assertRaises(ValueError):r.register_assemble_reveal_source(source)
        r.freeze()
        with self.assertRaises(ValueError):r.register_assemble_reveal_source(source)
        r=fixture.__wrapped__();r._cards[COPY_SOURCE]=replace(r.card(COPY_SOURCE),attack=99)
        with self.assertRaises(TargetValidationError):cards.register_assemble_native_copy_reveal_programs(r)

    def test_t_changed_native_request_and_late_selected_body_failure_roll_back_whole_action(self):
        for mode in('changed','suffix_fail'):
            cid=recipe(REVEAL,RUST);g=self.game((cid,),weapon=True,mode=mode);saved=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,cid)
            self.assertEqual(g.snapshot(),saved)


if __name__=='__main__':unittest.main()
