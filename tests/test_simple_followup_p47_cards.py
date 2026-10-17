"""One reviewed ten-root batch; explicit complete experimental fixture pools."""
from dataclasses import asdict, replace
from functools import lru_cache
import json, random, re, unittest
from unittest.mock import patch

from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p47_cards import (SENTRY,CHEF,SOOTHSAYER,TRIPWIRE,CLOCK,
    BRUISER,STARSURGE,JUDGMENT,EYES,ROOTS,DEPENDENCIES,SKIPPED,POOL_ID,load_batch,
    register_simple_followup_p47_cards)
from hs_sim.engine import (CardDefinition,CardMetadata,CardType,Game,IllegalAction,Keyword,
    PlayCard,PlayerSetup,Scenario,SelectChoice,TargetSpec,UseHandAction,EndTurn,Zone)
from hs_sim.engine.effects import (AddToHand,Buff,Damage,Destroy,Draw,ChoiceOption,
    InvokeBehavior,RequestChoice,Silence,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass,LimitedTriggerSpec,PlayerEffectSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.zones import AddToDeck
from hs_sim.targets import canonical_digest

TEST='p47.test.';YETI='CORE_CS2_182';TWO='CORE_GVG_085';SIX='CORE_BAR_310'
BEAST='CORE_EX1_028';LEGEND='BOT_411';PALADIN='CORE_CS2_093'
MEMBERS=(TWO,SIX,BEAST,LEGEND,PALADIN,YETI)
CONTEXT=GenerationContext('p47-complete-explicit-experiment','experimental')
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    present=tuple(cid in r.cards for cid in ROOTS+DEPENDENCIES)
    if not any(present):register_simple_followup_p47_cards(r)
    elif not all(present):raise AssertionError('P47 central assembly must contain the complete supported batch')
    register_candidate_pool_metadata(r);r.validate();return r

def registry(members=MEMBERS,mode=None,pool=True):
    r=batch_registry()
    for cid in members:
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p47-explicit-complete-fixture-v1',CONTEXT.target_id,
        CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    scripts={'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'hurt':lambda c:(Damage(c.target_id,2,c.source_id),),
        'wound':lambda c:(Damage(c.state.players[1].hero_id,12,c.source_id),),
        'buff':lambda c:(Buff(c.target_id,3,4,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'draw':lambda c:(Draw(1,source_id=c.source_id),),
        'neutral':lambda c:(AddToDeck(1,YETI,'top',c.source_id),),
        'sentry':lambda c:(Summon(1,SENTRY),),
        'fail':lambda c:(_ for _ in()).throw(ResolutionError('P47 deliberate continuation failure'))}
    for name,body in scripts.items():
        kwargs={} if name not in ('kill','hurt','buff','silence')else dict(targeting=TargetSpec(zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.MINION,CardType.HERO)))
        r.register_behavior(TEST+name,body)
        r.register_card(CardDefinition(TEST+name,name,CardType.SPELL,on_play=TEST+name,metadata=META,**kwargs))
    if mode:
        def eligible(c):
            return c.event.player_id==1 and any(root.request.cause.source.card_id in (SENTRY,TRIPWIRE,SOOTHSAYER)
                and any(d.outcome=='delivered'and d.entity.entity_id==c.event.target_id for d in root.deliveries)
                for root in c.state.card_summon_history)
        def watch(c):
            return (RequestChoice(1,(ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',
                (InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_trigger_condition(TEST+'eligible',eligible);r.register_behavior(TEST+'watch',watch)
        r.register_card(CardDefinition(TEST+'watch','Ordinary arrival continuation',CardType.MINION,health=9,
            metadata=META,limited_triggers=(LimitedTriggerSpec('minion_summoned',TEST+'watch',condition_id=TEST+'eligible',uses=4),)))
    r.validate();return r

@lru_cache(maxsize=None)
def shared_registry(members,mode,pool):return registry(members,mode,pool)

class SimpleFollowupP47Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),deck=(),enemy_deck=(YETI,)*6,members=MEMBERS,
            mode=None,pool=True,context=CONTEXT,mana=20,max_mana=20):
        self.config=(members,mode,pool)
        if mode:board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_04',hand=hand,board=board,deck=deck,
            mana=mana,max_mana=max_mana,mana_cap=50),PlayerSetup('HERO_08',board=enemy,deck=enemy_deck,
            mana=20,max_mana=20,mana_cap=50)),seed=4747,generation_context=context),shared_registry(*self.config))
    def first(self,g,cid,zone='hand',p=1):return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        e=self.first(g,cid);g.apply(PlayCard(1,e.id,target,position=len(g.state.players[1].board)if e.kind==CardType.MINION else None));return e.id
    def choose(self,g,key='ok'):g.apply(SelectChoice(1,g.state.pending_choice.id,(key,)))
    def ids(self,g,zone='board',p=1):return[g.state.entities[i].card_id for i in getattr(g.state.players[p],zone)]
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry(*self.config))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for k in('rng_state','resolution_frame','pool_id','behavior_id','rewind_session','card_summon_history'):
                self.assertNotIn('"'+k+'"',public)
        return other

    def test_complete_eleven_rows_twenty_two_faces_metadata_school_and_reviewed_dynamic_number(self):
        d=load_batch();r=batch_registry();rows=d['cards']+d['dependencies']+d['skipped']
        self.assertEqual((len(rows),len(d['official_observations'])),(11,22))
        norm=lambda s:re.sub(r'\s+|<[^>]+>|\[x\]|[$&_#]','',s)
        for row in rows:
            raw=row['record'];cid=raw['id'];self.assertEqual(canonical_digest(raw),row['record_sha256'])
            if cid not in SKIPPED:
                c=r.card(cid);self.assertEqual(c.metadata,metadata_from_record(raw));self.assertEqual(c.cost,raw['cost'])
                self.assertEqual((c.attack,c.health),(raw['attack']or 0,raw['health']or 0))
                self.assertEqual(c.spell_school.value if c.spell_school else None,row['spell_school'])
            observations=[o for o in d['official_observations']if o['card_id']==cid];self.assertEqual(len(observations),2)
            for o in observations:
                f=o['face'];en=o['locale']=='en_US';text=raw['text_en'if en else'text']
                if cid==STARSURGE:text=text.replace('@','')
                self.assertEqual(norm(f['text']),norm(text));self.assertEqual(f['name'],raw['name_en'if en else'name'])
                self.assertEqual((f['id'],f['manaCost']),(raw['dbf_id'],raw['cost']))
                self.assertFalse(re.match(r'^[A-Za-z]:',o['response_file']))
        self.assertEqual(next(x['record']for x in rows if x['record']['id']==STARSURGE)['tags']['TAG_SCRIPT_DATA_NUM_1'],1)
        self.assertEqual(r.card(CLOCK).rewind.retries,3);self.assertIsNotNone(r.card(DEPENDENCIES[0]).cast_when_drawn)
        self.assertEqual(d['scope']['cn_calibrated'],False);self.assertFalse(d['scope']['formal_pool_complete'])

    def test_all_existing_complete_definitions_pool_rows_families_and_default_preserved(self):
        with patch('hs_sim.cards.simple_followup_p47_cards.register_simple_followup_p47_cards',lambda r:None):before=build_registry()
        after=batch_registry()
        self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS+DEPENDENCIES))
        for cid,c in before.cards.items():self.assertEqual(asdict(c),asdict(after.card(cid)))
        for cid,c in before.pool_cards.items():self.assertEqual(c,after.pool_card(cid))
        self.assertEqual(dict(before.pools),dict(after.pools));self.assertEqual(dict(before.generation_families),dict(after.generation_families))
        from hs_sim.engine.representative import build_registry as default
        self.assertEqual(default().fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_real_aura_zone_capability_probe_rejects_kind_and_keeps_whole_root_missing(self):
        r=batch_registry()
        with self.assertRaisesRegex(ValueError,'Unsupported player effect kind'):
            PlayerEffectSpec('p47.probe','TIME_019',kind='aura',duration=3,tick_event='turn_ended')
        self.assertNotIn('TIME_019',r.cards);self.assertIn('TIME_019',r.pool_cards)

    def test_sentry_current_no_neutral_and_ordinary_capacity_summons_without_recursive_battlecry(self):
        for deck,extra in(((),2),((PALADIN,),2),((YETI,),0)):
            with self.subTest(deck=deck):
                g=self.game((SENTRY,),deck=deck,pool=False,context=None);self.play(g,SENTRY)
                self.assertEqual(self.ids(g).count(SENTRY),1+extra);self.assertEqual(len(g.state.battlecry_history),1)
        g=self.game((SENTRY,),board=(YETI,)*5,pool=False,context=None);self.play(g,SENTRY)
        self.assertEqual(len(self.ids(g)),7);self.assertEqual(self.ids(g).count(SENTRY),2)
        g=self.game((TEST+'sentry',),pool=False,context=None);self.play(g,TEST+'sentry')
        self.assertEqual(self.ids(g),[SENTRY]);self.assertFalse(g.state.battlecry_history)

    def test_sentry_two_independent_arrival_waits_restore_and_failed_resume_rollback(self):
        g=self.game((SENTRY,),mode='wait',pool=False,context=None);self.play(g,SENTRY)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for x in(g,other):self.choose(x);self.choose(x)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.ids(g).count(SENTRY),3)

    def test_chef_native_printed_taunt_two_or_six_uses_total_crystals_after_payment(self):
        for total,mana,expected in((9,9,TWO),(10,10,SIX),(10,3,SIX)):
            with self.subTest(total=total,mana=mana):
                g=self.game((CHEF,),members=(TWO,SIX,YETI),mana=mana,max_mana=total);self.play(g,CHEF)
                self.assertEqual(self.ids(g),[CHEF,expected]);self.assertIn(Keyword.TAUNT,self.first(g,expected,'board').keywords)
                self.assertEqual(g.state.players[1].mana,mana-3)

    def test_soothsayer_real_death_heals_six_then_summons_six_at_original_slot(self):
        g=self.game((TEST+'wound',TEST+'kill'),board=(YETI,SOOTHSAYER,YETI),members=(SIX,));hero=g.state.players[1].hero_id
        self.play(g,TEST+'wound');self.play(g,TEST+'kill',self.first(g,SOOTHSAYER,'board').id)
        self.assertEqual(self.ids(g),[YETI,SIX,YETI]);self.assertEqual(g.state.entities[hero].health,24)
        self.assertEqual(g.state.healing_history[-1].health_result.base_amount,6)
        events=[e.kind for e in g.events];self.assertLess(events.index('healed'),len(events)-1-events[::-1].index('minion_summoned'))

    def test_native_prepare_for_both_faces_pays_once_locks_current_turn_and_discounts_next_turn(self):
        for cid in(SOOTHSAYER,JUDGMENT):
            with self.subTest(cid=cid):
                g=self.game((cid,),board=(YETI,),members=(SIX,),deck=(PALADIN,)*3,mana=1)
                source=self.first(g,cid).id;g.apply(UseHandAction(1,source,'prepare'))
                self.assertEqual(g.state.players[1].mana,0)
                with self.assertRaises(IllegalAction):g.apply(PlayCard(1,source,self.first(g,YETI,'board').id if cid==JUDGMENT else None,position=1 if cid==SOOTHSAYER else None))
                g.apply(EndTurn(1));g.apply(EndTurn(2));before=g.state.players[1].mana
                self.play(g,cid,self.first(g,YETI,'board').id if cid==JUDGMENT else None)
                self.assertEqual(before-g.state.players[1].mana,g.registry.card(cid).cost-2)

    def test_tripwire_random_five_beast_then_one_semantic_two_token_shuffle(self):
        g=self.game((TRIPWIRE,),deck=(PALADIN,YETI,PALADIN),members=(BEAST,SIX,YETI));self.play(g,TRIPWIRE)
        self.assertEqual(self.ids(g),[BEAST]);self.assertEqual(self.ids(g,'deck').count(DEPENDENCIES[0]),2)
        self.assertEqual(len([e for e in g.events if e.kind=='card_added_to_deck']),2)
        row,=g.state.deck_shuffle_history;self.assertEqual((row.profile,row.declared_count,row.player_id,row.actor_id),('semantic',2,1,1))

    def test_tripwire_wait_preserves_pending_shuffle_and_drawn_token_autocasts_with_real_replacement(self):
        g=self.game((TRIPWIRE,),deck=(PALADIN,),members=(BEAST,),mode='wait');self.play(g,TRIPWIRE)
        self.assertEqual(self.ids(g,'deck'),[PALADIN]);other=self.portable(g)
        for x in(g,other):self.choose(x)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.ids(g,'deck').count(DEPENDENCIES[0]),2)
        g=self.game((TEST+'draw',),deck=(DEPENDENCIES[0],PALADIN),members=(BEAST,));token_id=g.state.players[1].deck[0]
        self.play(g,TEST+'draw');self.assertEqual(self.ids(g),[BEAST]);self.assertEqual(self.ids(g,'hand'),[PALADIN])
        self.assertEqual(g.state.entities[token_id].zone,Zone.GRAVEYARD);self.assertEqual(g.state.players[1].mana,20)
        self.assertEqual([r.card_id for r in g.state.cast_history],[TEST+'draw',DEPENDENCIES[0]])
        self.assertEqual(len(g.state.draw_history),2);self.assertIsNotNone(g.state.draw_history[0].replacement_id)

    def test_triple_rewind_three_actual_retries_only_two_committed_legendaries_one_payment(self):
        g=self.game((CLOCK,),members=(LEGEND,));source=self.play(g,CLOCK);other=self.portable(g)
        for x in(g,other):
            for _ in range(3):
                self.assertIsNotNone(x.state.pending_choice);self.choose(x,'retry')
            self.assertIsNone(x.state.pending_choice)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.ids(g),[CLOCK,LEGEND,LEGEND])
        self.assertEqual(g.state.players[1].mana,12);self.assertEqual(len(g.state.battlecry_history),1)
        self.assertEqual(g.state.players[1].board[0],source)

    def test_bruiser_current_physical_deck_condition_and_random_paladin_cost_minus_two(self):
        for deck,expected in(((),True),((PALADIN,),True),((YETI,),False)):
            with self.subTest(deck=deck):
                g=self.game((TEST+'kill',),board=(BRUISER,),deck=deck,members=(PALADIN,YETI));self.play(g,TEST+'kill',self.first(g,BRUISER,'board').id)
                self.assertEqual(self.ids(g,'hand'),[PALADIN]if expected else [])
                if expected:self.assertEqual(g.quote_cost(self.first(g,PALADIN).id).amount,max(0,g.registry.card(PALADIN).cost-2))
        g=self.game((TEST+'neutral',TEST+'kill'),board=(BRUISER,),members=(PALADIN,));self.play(g,TEST+'neutral');self.play(g,TEST+'kill',self.first(g,BRUISER,'board').id);self.assertFalse(self.ids(g,'hand'))

    def test_starsurge_base_one_actual_friendly_deaths_and_normal_spell_power(self):
        for friendly,enemy in((0,0),(2,1)):
            with self.subTest(friendly=friendly,enemy=enemy):
                g=self.game((TEST+'kill',)*(friendly+enemy)+(STARSURGE,),board=(YETI,)*friendly,enemy=(YETI,)*(enemy+1),pool=False,context=None)
                for _ in range(friendly):self.play(g,TEST+'kill',self.first(g,YETI,'board').id)
                for _ in range(enemy):self.play(g,TEST+'kill',self.first(g,YETI,'board',2).id)
                target=self.first(g,YETI,'board',2).id;self.play(g,STARSURGE,target)
                self.assertEqual(g.state.entities[target].health,5-(1+friendly))
        g=self.game((STARSURGE,),board=('CORE_EX1_012',),enemy=(YETI,),pool=False,context=None)
        target=self.first(g,YETI,'board',2).id;self.play(g,STARSURGE,target);self.assertEqual(g.state.entities[target].health,3)

    def test_judgment_original_current_selected_values_all_sides_stat_layers_and_friendly_target(self):
        g=self.game((TEST+'buff',TEST+'hurt',JUDGMENT,TEST+'silence'),board=(YETI,TWO),enemy=(SIX,),pool=False,context=None)
        target=self.first(g,TWO,'board').id;self.play(g,TEST+'buff',target);self.play(g,TEST+'hurt',target)
        selected=g.state.entities[target];expected=(selected.attack,selected.health);self.play(g,JUDGMENT,target)
        for p in(1,2):
            for i in g.state.players[p].board:self.assertEqual((g.state.entities[i].attack,g.state.entities[i].health),expected)
        self.play(g,TEST+'silence',self.first(g,YETI,'board').id)
        self.assertEqual((self.first(g,YETI,'board').attack,self.first(g,YETI,'board').health),(4,5))
        g=self.game((JUDGMENT,),enemy=(YETI,),pool=False,context=None);saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,JUDGMENT,self.first(g,YETI,'board',2).id)
        self.assertEqual(g.snapshot(),saved)

    def test_eyes_samples_full_physical_enemy_deck_and_moves_original_selected_entity_top_privately(self):
        deck=(YETI,TWO,BEAST,SIX,LEGEND,PALADIN)
        g=self.game((EYES,),enemy_deck=deck,pool=False,context=None);original=g.state.players[2].deck[:]
        rng=random.Random();rng.setstate(g._rng.getstate());offered=rng.sample(original,3)
        self.play(g,EYES);pending=g.state.pending_choice;self.assertEqual(len(pending.options),3)
        self.assertEqual([o.card_id for o in pending.options],[g.state.entities[i].card_id for i in offered])
        self.assertEqual(g._rng.getstate(),rng.getstate());self.assertTrue(any(i not in original[-3:]for i in offered))
        public=json.dumps(g.for_player(2).observe())+json.dumps(g.for_player(2).legal_actions())+json.dumps(g.player_events(2))
        for o in pending.options:
            self.assertNotIn('"'+o.card_id+'"',public);self.assertNotIn(json.dumps(o.label),public)
        other=self.portable(g);alternative=g.clone();self.choose(alternative,pending.options[0].id)
        key=pending.options[1].id;selected=offered[1]
        for x in(g,other):self.choose(x,key)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.players[2].deck,[selected]+[i for i in original if i!=selected])
        self.assertEqual(g.state.players[1].hand,[]);self.assertEqual(g._rng.getstate(),rng.getstate())
        self.assertEqual(g.for_player(2).observe(),alternative.for_player(2).observe())
        self.assertEqual(g.player_events(2),alternative.player_events(2))
        self.assertEqual(g.for_player(2).legal_actions(),alternative.for_player(2).legal_actions())
        public=json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2))
        for o in pending.options:self.assertNotIn('"'+o.card_id+'"',public)
        for p in(1,2):
            moved=[e for e in g.player_events(p)if e['kind']=='card_moved_to_deck'];self.assertEqual(len(moved),1)
            self.assertIsNone(moved[0]['target']);self.assertNotIn('card_id',moved[0])

    def test_judgment_waiting_stat_reaction_cannot_rebind_same_entity_after_return_and_reentry(self):
        from hs_sim.engine.colossal import SummonStoredCard
        from hs_sim.engine.effects import ReturnToHand
        from hs_sim.engine.zones import CardReference
        def fresh():
            r=registry(pool=False)
            def reenter(c):
                return(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id),)
            def original(c):
                return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==JUDGMENT
            def watch(c):
                target=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==TWO)
                return(RequestChoice(1,(ChoiceOption('reenter','Return then reenter',(
                    ReturnToHand(target),InvokeBehavior(TEST+'review_reenter',c.source_id,1,target))),),c.source_id),)
            r.register_behavior(TEST+'review_reenter',reenter);r.register_behavior(TEST+'review_watch',watch)
            r.register_trigger_condition(TEST+'review_original',original)
            r.register_card(CardDefinition(TEST+'review_watch','One real stat reaction',CardType.MINION,health=9,
                metadata=META,limited_triggers=(LimitedTriggerSpec('stats_changed',TEST+'review_watch',
                    condition_id=TEST+'review_original',uses=1),)))
            r.validate();return r
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_04',hand=(JUDGMENT,),board=(YETI,TWO,TEST+'review_watch'),
            mana=10,max_mana=10),PlayerSetup('HERO_08'))),fresh())
        old=g.state.players[1].board[1];presence=g.state.entities[old].board_presence_id
        self.play(g,JUDGMENT,g.state.players[1].board[0]);self.assertIsNotNone(g.state.pending_choice)
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,fresh())
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),fresh()).snapshot(),saved)
        for x in(g,other):
            self.choose(x,'reenter');e=x.state.entities[old]
            self.assertNotEqual(e.board_presence_id,presence)
            self.assertEqual((e.attack,e.health),(1,2))
            self.assertEqual(x.state.players[1].board[-1],old)
        self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(replay(build_replay(g),fresh()).snapshot(),g.snapshot())

    def test_eyes_duplicate_physical_weights_empty_and_short_decks(self):
        for deck in((),(YETI,),(YETI,YETI,TWO,BEAST,SIX)):
            with self.subTest(deck=deck):
                g=self.game((EYES,),enemy_deck=deck,pool=False,context=None);before=g._rng.getstate();original=g.state.players[2].deck[:];self.play(g,EYES)
                if not deck:self.assertIsNone(g.state.pending_choice);self.assertEqual(g._rng.getstate(),before)
                else:
                    pending=g.state.pending_choice;self.assertEqual(len(pending.options),min(3,len(deck)));self.choose(g,pending.options[0].id)
                    self.assertEqual(set(g.state.players[2].deck),set(original))

    def test_all_generation_boundaries_unknown_eligible_fail_before_rng_and_rollback(self):
        r=batch_registry()
        conditions=((CHEF,lambda c:c.kind==CardType.MINION and c.cost==6 and Keyword.TAUNT in c.keywords),
            (SOOTHSAYER,lambda c:c.kind==CardType.MINION and c.cost==6),
            (TRIPWIRE,lambda c:c.kind==CardType.MINION and c.cost==5 and 'beast'in c.metadata.tribes),
            (CLOCK,lambda c:c.kind==CardType.MINION and c.metadata.rarity and c.metadata.rarity.value=='legendary'),
            (BRUISER,lambda c:CardClass.PALADIN in c.metadata.classes))
        for cid,predicate in conditions:
            unknown=next(c.card_id for c in r.pool_cards.values()if c.card_id not in r.cards and c.metadata.collectible and predicate(c))
            with self.subTest(cid=cid,unknown=unknown):
                death=cid in(SOOTHSAYER,BRUISER);g=self.game((TEST+'kill',)if death else(cid,),board=(cid,)if death else(),members=(unknown,))
                saved=g.snapshot();calls=[];original=random.Random.randrange
                def spy(r,*a,**kw):calls.append(a);return original(r,*a,**kw)
                with patch.object(random.Random,'randrange',autospec=True,side_effect=spy):
                    with self.assertRaises(ResolutionError):self.play(g,TEST+'kill',self.first(g,cid,'board').id)if death else self.play(g,cid)
                self.assertFalse(calls);self.assertEqual(g.snapshot(),saved)

if __name__=='__main__':unittest.main()
