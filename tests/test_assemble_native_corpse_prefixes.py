"""Selected native providers, actual corpse receipts and success-only suffixes."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import json,unittest

from hs_sim.cards import assemble_native_corpse_prefixes as cards
from hs_sim.cards.constructed import build_registry
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.native_assemble_entry_cards import POOL_ID
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,DeckPolicy,DeckSpec,Game,
    MatchSetup,OpeningHook,PlayCard,PlayerSetup,Rarity,Runes,Scenario,SelectChoice,SnapshotError,TargetSpec,Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.assemble_offers import recipe_options
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChangeManaCrystals,ChoiceOption,CopyMinion,
    Destroy,GainResource,InvokeBehavior,RequestChoice,ReturnToHand,Silence,SpendResource,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec,Resource
from hs_sim.engine.pools import PoolDefinition,PoolMember,GenerationContext
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError,canonical_digest
from tools.card_batch import check_face,sha

FALRIC,HEM=cards.SOURCES
RUST,LOOT,PRIMORDIAL,CLEANER,BEAST,BLOOD_A,BLOOD_B,BLOOD_C,PHOENIX=cards.DEPENDENCIES
BLOODS=(BLOOD_A,BLOOD_B,BLOOD_C)
P='k446.'
N,KILL,MUTE,COPY,BASE,CONTROL,GAIN,WATCH,FAIL,REENTER=(P+x for x in(
    'n','kill','mute','copy','base','control','gain','watch','fail','reenter'))
COIN='GAME_005';BOOT=P+'boot';YETI='CORE_CS2_182'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
CTX=GenerationContext('k446-complete-reviewed-native-corpse-domains','experimental')


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
    r=build_registry();r._version+='.k446.'+mode
    r.register_card(CardDefinition(N,N,CardType.MINION,attack=1,health=20,metadata=META))
    def fail(c):raise ResolutionError('K446 deliberate late payment suffix failure')
    def reenter(c):return(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id),)
    r.register_behavior(FAIL,fail);r.register_behavior(REENTER,reenter)
    scripts={KILL:lambda c:(Destroy(c.target_id,c.source_id),),MUTE:lambda c:(Silence(c.target_id),),
        COPY:lambda c:(CopyMinion(c.target_id,1,mode='current'),),BASE:lambda c:(CopyMinion(c.target_id,1,mode='base'),),
        CONTROL:lambda c:(ChangeControl(c.target_id,2),),GAIN:lambda c:(GainResource(1,Resource.CORPSES,1),)}
    for cid,fn in scripts.items():
        r.register_behavior(cid,fn);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=META,
            targeting=None if cid==GAIN else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    if mode in('pay_wait','nested','new_minion','reenter'):
        def watch(c):
            if mode=='nested':return(SpendResource(1,Resource.CORPSES,1),)
            if mode=='new_minion':return(Summon(1,N),)
            if mode=='reenter':
                active=next(b for b in reversed(c.state.battlecry_history)if b.player_id==1 and not b.completed)
                return(ReturnToHand(active.source_id),InvokeBehavior(REENTER,c.source_id,1,active.source_id))
            return(RequestChoice(1,(ChoiceOption('go','Continue'),ChoiceOption('bad','Fail',(InvokeBehavior(FAIL,c.source_id,1),))),c.source_id),)
        r.register_behavior(WATCH,watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,metadata=META,
            limited_triggers=(LimitedTriggerSpec('resource_spent',WATCH),)))
    original=r.behavior(r.card(RUST).battlecry)
    def audited(c):
        if c.paid_battlecry_followup is not None:
            link=c.paid_battlecry_followup
            if c.source!=link.accepted.source or link.payment_id is None:raise ResolutionError('Paid body lost source or receipt')
            if mode=='nested'and link.payment_id!=1:raise ResolutionError('Paid body borrowed nested payment')
            if mode=='reenter'and c.source.zone_epoch==c.state.entities[c.source_id].zone_epoch:
                raise ResolutionError('Paid body rebound to the reentered incarnation')
            if mode=='suffix_fail':raise ResolutionError('K446 actual selected suffix failure')
        return original(c)
    r._behaviors[r.card(RUST).battlecry]=audited
    r.register_pool(PoolDefinition('constructed.cards','k446-three-complete-Blood-candidates',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in BLOODS),complete=True))
    domains={'paid_offer':(HEM,BEAST,CLEANER),'gain_offer':(FALRIC,BEAST,CLEANER)}
    if mode in domains:r.register_pool(PoolDefinition(POOL_ID,'k446-three-exact-native-fragments',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in domains[mode]),complete=True))
    if mode=='gain_offer':
        def boot(c):
            return (ChangeManaCrystals(c.player_id,10,filled=True),AddToHand(1,MISMATCH,c.source_id),
                AddToHand(1,KILL,c.source_id),Summon(1,N)) if c.player_id==1 else ()
        r.register_behavior(BOOT,boot);r.register_card(CardDefinition(BOOT,BOOT,CardType.MINION,health=1,
            metadata=replace(META,collectible=True,rarity=Rarity.COMMON,runes=Runes()),
            opening_hooks=(OpeningHook('after_mulligan',BOOT),)))
    r.validate();return r


class AssembleNativeCorpseTests(unittest.TestCase):
    def game(self,hand=(),board=(),deck=(HEM,)+(COIN,)*16,corpses=0,mode='normal',weapon=False,enemy=()):
        if mode in('pay_wait','nested','new_minion','reenter'):board=board+(WATCH,)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_11',hand=hand,board=board,deck=deck,
            mana=20,max_mana=20,mana_cap=40,corpses=corpses),PlayerSetup('HERO_08',board=enemy,deck=(COIN,)*16,
                weapon_card_id='CS2_091'if weapon else None)),seed=6,generation_context=CTX),fixture(mode))

    def ids(self,g,cid,zone='board',p=1):return[i for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid]
    def play(self,g,cid,target=None):
        source=self.ids(g,cid,'hand')[0];g.apply(PlayCard(1,source,target));return source
    def corpse(self,g,p=1):return g.state.players[p].resources.get(Resource.CORPSES,0)
    def choose(self,g,key=None):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key or q.options[0].id,)))
    def portable(self,g,mode='normal'):
        saved=json.loads(json.dumps(g.snapshot()));reader=fixture(mode,'reader');self.assertIsNot(reader,g.registry)
        other=Game.from_snapshot(saved,reader);self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),reader).snapshot(),saved);self.assertEqual(g.snapshot(),saved)
        for p in(1,2):
            text=json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for key in('paid_battlecry_followup','AssemblePaidBattlecryContinuation','resolution_frame','rng_state'):
                self.assertNotIn('"'+key+'"',text)
        return other

    def test_a_complete_eleven_rows_twenty_two_faces_and_exact_original_self_definitions(self):
        d=cards.load_batch();r=fixture();rows={x['record']['id']:x for x in d['existing_dependencies']}
        self.assertEqual((len(rows),len(d['official_observations'])),(11,22))
        for o in d['official_observations']:
            self.assertEqual(sha(o['response_file']),o['response_sha256']);check_face(rows[o['card_id']]['record'],o['face'],o['locale'],d['display_normalizations'].get(o['card_id']))
        for cid,row in rows.items():self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
        for cid in cards.SOURCES:
            old=asdict(r.card(cid));new=asdict(r.card(recipe(cid)));new['id']=cid
            self.assertEqual(old,new);self.assertEqual(recipe_options(r,cid,cid),())

    def test_b_raw_and_self_falric_keep_native_printed_gain_provider_and_death_credit(self):
        for cid in(FALRIC,recipe(FALRIC)):
            g=self.game((KILL,),(cid,N));source=self.ids(g,cid)[0]
            self.assertEqual([a.corpse_gain_card_id for a in g.state.entities[source].abilities if a.kind=='corpse_gain'],[FALRIC])
            self.play(g,KILL,self.ids(g,N)[0]);self.assertEqual(self.corpse(g),2)

    def test_c_provider_stays_with_selected_prefix_even_when_primary_is_another_card(self):
        cid=recipe(RUST,FALRIC,'top');g=self.game((cid,KILL),(N,),weapon=True);self.play(g,cid)
        self.assertIsNone(g.state.players[2].weapon_id);self.play(g,KILL,self.ids(g,N)[0]);self.assertEqual(self.corpse(g),2);self.portable(g)

    def test_d_replacing_provider_prefix_keeps_original_spender_draw_without_double_gain(self):
        cid=recipe(FALRIC,RUST,'top');g=self.game((cid,KILL),(N,));self.play(g,cid)
        self.assertEqual(len(self.ids(g,HEM,'hand')),1);self.play(g,KILL,self.ids(g,N)[0]);self.assertEqual(self.corpse(g),1)

    def test_e_silenced_current_copy_stays_silenced_but_base_copy_restores_printed_provider(self):
        cid=recipe(FALRIC);g=self.game((MUTE,COPY,BASE,GAIN),(cid,));source=self.ids(g,cid)[0]
        self.play(g,MUTE,source);self.play(g,COPY,source);self.play(g,BASE,source);self.play(g,GAIN)
        self.assertEqual(self.corpse(g),2);self.portable(g)

    def test_f_two_printed_providers_multiply_and_control_changes_actual_recipient(self):
        cid=recipe(FALRIC);g=self.game((COPY,GAIN,CONTROL,GAIN),(cid,));source=self.ids(g,cid)[0]
        self.play(g,COPY,source);self.play(g,GAIN);self.assertEqual(self.corpse(g),4)
        self.play(g,CONTROL,source);self.play(g,GAIN);self.assertEqual(self.corpse(g),6);self.portable(g)

    def test_g_native_and_self_hematurge_only_pay_actual_one_then_offer_complete_blood_pool(self):
        for cid in(HEM,recipe(HEM)):
            for bank in(0,1):
                g=self.game((cid,),corpses=bank);self.play(g,cid)
                self.assertEqual(self.corpse(g),0);self.assertEqual(g.state.pending_choice is not None,bool(bank))
                if bank:
                    self.assertEqual({o.card_id for o in g.state.pending_choice.options},set(BLOODS));self.choose(g)

    def test_h_replacing_paid_prefix_makes_discovery_independent_of_corpse_payment(self):
        cid=recipe(HEM,RUST,'top');g=self.game((cid,),corpses=0);self.play(g,cid)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.corpse_spend_history,[]);self.choose(g)

    def test_i_paid_prefix_gates_weapon_suffix_and_drops_original_discovery(self):
        cid=recipe(HEM,RUST)
        for bank in(0,2):
            g=self.game((cid,),corpses=bank,weapon=True);self.play(g,cid)
            self.assertEqual(g.state.players[2].weapon_id is None,bool(bank));self.assertIsNone(g.state.pending_choice)
            self.assertEqual(self.corpse(g),0 if not bank else bank-1)

    def test_j_paid_suffix_reads_minion_created_by_actual_resource_notification(self):
        cid=recipe(HEM,BEAST);g=self.game((cid,),corpses=1,mode='new_minion');source=self.play(g,cid)
        self.assertEqual(g.state.entities[source].attack,g.registry.card(HEM).attack+3)
        self.assertEqual(g.state.entities[self.ids(g,N)[0]].attack,4);self.assertEqual(self.corpse(g),0);self.portable(g,'new_minion')

    def test_k_original_selected_target_survives_success_gate_without_extra_debit(self):
        cid=recipe(HEM,PHOENIX);g=self.game((cid,),corpses=1,enemy=(N,));target=self.ids(g,N,p=2)[0]
        self.play(g,cid,target);self.assertEqual(g.state.entities[target].health,17)
        self.assertEqual(len(g.state.corpse_spend_history),1);self.portable(g)

    def test_l_resource_notification_wait_binds_payment_before_wait_and_never_repays(self):
        cid=recipe(HEM,RUST);g=self.game((cid,),corpses=1,mode='pay_wait',weapon=True);self.play(g,cid)
        self.assertEqual(self.corpse(g),0);self.assertIsNotNone(g.state.players[2].weapon_id);reader=self.portable(g,'pay_wait');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'go');self.choose(reader,'go');self.assertEqual(g.snapshot(),reader.snapshot())
        self.assertEqual(len(g.state.corpse_spend_history),1);self.assertIsNone(g.state.players[2].weapon_id)

    def test_m_nested_payment_does_not_replace_original_success_receipt(self):
        cid=recipe(HEM,RUST);g=self.game((cid,),corpses=3,mode='nested',weapon=True);self.play(g,cid)
        self.assertEqual((len(g.state.corpse_spend_history),self.corpse(g)),(2,1));self.assertIsNone(g.state.players[2].weapon_id);self.portable(g,'nested')

    def test_n_source_reentry_keeps_original_source_view_and_one_battlecry(self):
        cid=recipe(HEM,RUST);g=self.game((cid,),corpses=1,mode='reenter',weapon=True);source=self.play(g,cid)
        self.assertIn(source,g.state.players[1].board);self.assertIsNone(g.state.players[2].weapon_id)
        self.assertEqual((len(g.state.battlecry_history),len(g.state.corpse_spend_history)),(1,1));self.portable(g,'reenter')

    def test_o_late_selected_body_failure_rolls_back_mana_debit_and_all_records(self):
        cid=recipe(HEM,RUST);g=self.game((cid,),corpses=1,mode='suffix_fail',weapon=True);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,cid)
        self.assertEqual(g.snapshot(),saved)

    def test_p_rehashed_paid_continuation_cannot_borrow_future_payment_or_another_body(self):
        cid=recipe(HEM,RUST);g=self.game((cid,),corpses=1,mode='pay_wait');self.play(g,cid);saved=g.snapshot()
        self.assertTrue(list(nodes(saved,'AssemblePaidBattlecryContinuation')))
        for change in('future','body','player'):
            bad=deepcopy(saved);m=next(n for n in nodes(bad,'AssemblePaidBattlecryContinuation')if n['fields']['payment_id']is not None)['fields']
            if change=='future':m['payment_id']=999
            elif change=='body':m['behavior_id']=cards.PREFIX+'discover'
            else:m['accepted']['fields']['player_id']=2
            with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture('pay_wait','reader'))

    def test_q_true_low_cost_offer_uses_original_paid_prefix_and_current_buff_body(self):
        cid=recipe(HEM,BEAST);g=self.game((MISMATCH,),corpses=1,mode='paid_offer');self.play(g,MISMATCH)
        q=g.state.pending_choice;self.assertIn(cid,[o.card_id for o in q.options]);self.portable(g,'paid_offer')
        self.choose(g,next(o.id for o in q.options if o.card_id==cid));source=self.play(g,cid)
        self.assertEqual(g.state.entities[source].attack,g.registry.card(HEM).attack+3);self.assertEqual(self.corpse(g),0);self.portable(g,'paid_offer')

    def test_r_true_provider_offer_preserves_multiplier_while_replacing_draw_body(self):
        cid=recipe(FALRIC,CLEANER);policy=DeckPolicy('k446-opening',CTX.target_id,CTX.mode,
            (BOOT,YETI),deck_size=12,max_copies=12)
        deck=DeckSpec('HERO_11','HERO_11bp',CardClass.DEATH_KNIGHT,(BOOT,)+(YETI,)*11,
            runes=Runes(blood=1,unholy=2))
        g=Game.from_decks(MatchSetup((deck,deck),policy,COIN,seed=6,first_player=1),fixture('gain_offer'))
        while g.state.pending_choice:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        self.assertIsNotNone(g.state.opening);self.play(g,MISMATCH)
        q=g.state.pending_choice;self.assertIn(cid,[o.card_id for o in q.options]);self.choose(g,next(o.id for o in q.options if o.card_id==cid))
        self.play(g,cid);self.play(g,KILL,self.ids(g,N)[0]);self.assertEqual(self.corpse(g),2);self.portable(g,'gain_offer')

    def test_s_provider_profile_and_paid_profile_are_unique_readonly_and_frozen(self):
        r=fixture.__wrapped__();gain=r.assemble_corpse_gain_sources[FALRIC];paid=r.assemble_paid_battlecry_sources[HEM]
        with self.assertRaises(TypeError):r.assemble_corpse_gain_sources[FALRIC]=gain
        with self.assertRaises(ValueError):r.register_assemble_corpse_gain_source(gain)
        with self.assertRaises(ValueError):r.register_assemble_paid_battlecry_source(paid)
        r.freeze()
        with self.assertRaises(ValueError):r.register_assemble_paid_battlecry_source(paid)

    def test_t_missing_native_material_and_changed_complete_source_fail_explicitly(self):
        r=fixture.__wrapped__();del r._assemble_corpse_gain_sources[FALRIC]
        with self.assertRaises(ValueError):r.card(recipe(RUST,FALRIC,'top'))
        r=fixture.__wrapped__();r._cards[HEM]=replace(r.card(HEM),attack=99)
        with self.assertRaises(TargetValidationError):cards.register_assemble_native_corpse_prefixes(r)


if __name__=='__main__':unittest.main()
