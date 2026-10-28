"""Original physical deck plans and original live hand-commit copy material."""
from dataclasses import replace
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from tools import card_batch as batch
from hs_sim.cards import ignite_card,secret_original_sources as native
from hs_sim.engine import EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Damage,Draw,GainArmor,InvokeBehavior,RandomDamage,
    RequestChoice,ReturnToHand)
from hs_sim.engine.model import CardClass,CardDefinition,CardType,Keyword,SecretSpec,TargetSpec,Zone,TriggerSpec
from hs_sim.engine.native_spell_values import public_value
from hs_sim.engine.secret_source_operations import CopyCommittedHandCard,InstallDeckSecrets
from hs_sim.engine.secrets import RemoveSecret,SetSecret
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import AddToDeck,CardReference
from hs_sim.local_pool_format import build_cn37_local_pool_format

BOOK,VEIN=native.LEAVES;IGNITE=ignite_card.CARD;P='k631.'
MINION,BC,SPELL,WEAPON,HERO,LOCATION,FILL=(P+x for x in('minion','battlecry','spell','weapon','hero','location','fill'))
SECRETS=tuple(P+'secret'+str(i) for i in range(7));ALIAS=P+'alias'
NOOP,FALSE,FAIL,WAIT,DRAW,GET,SET,BOUNCE,AUTO,OLD_COPY=(P+x for x in
    ('noop','false','fail','wait','draw','get','set','bounce','auto','old_copy'))


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=opening_registry();native.register_secret_original_sources(r);ignite_card.register_ignite_card(r)
    r.register_behavior(NOOP,lambda c:());r.register_secret_condition(FALSE,lambda c:False)
    for cid,key in ((*((cid,cid) for cid in SECRETS),(ALIAS,SECRETS[0]))):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1,keywords=(Keyword.SECRET,),
            secret=SecretSpec(key,('card_played',),FALSE,NOOP),metadata=metadata(CardClass.MAGE,tribes=())))
        setup=P+'setup.'+cid
        r.register_behavior(setup,lambda c,cid=cid:(SetSecret(1,cid),))
        r.register_card(CardDefinition(setup,setup,CardType.SPELL,on_play=setup,metadata=metadata(tribes=())))
    r.register_card(CardDefinition(MINION,MINION,CardType.MINION,cost=1,attack=2,health=5,metadata=metadata(tribes=())))
    r.register_card(CardDefinition(FILL,FILL,CardType.MINION,cost=1,attack=1,health=10,metadata=metadata(tribes=())))
    def battlecry(c):
        copies=[c.state.entities[i] for i in c.state.players[1].hand if c.state.entities[i].card_id==BC]
        if not copies or copies[0].cost!=0:raise ResolutionError('Azerite copy was not delivered before the original Battlecry')
        return (GainArmor(c.player_id,1),)
    r.register_behavior(BC,battlecry)
    r.register_card(CardDefinition(BC,BC,CardType.MINION,cost=1,attack=2,health=5,battlecry=BC,metadata=metadata(tribes=())))
    r.register_behavior(SPELL,lambda c:(Damage(c.state.players[1].hero_id,1,c.source_id),))
    r.register_card(CardDefinition(SPELL,SPELL,CardType.SPELL,cost=1,on_play=SPELL,metadata=metadata(CardClass.MAGE,tribes=())))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,cost=1,attack=2,durability=3,metadata=metadata(tribes=())))
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,cost=1,health=30,hero_card=True,
        initial_hero_power='warrior.power',metadata=metadata(CardClass.WARRIOR,tribes=())))
    r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,cost=1,durability=3,on_use=NOOP))
    scripts={DRAW:lambda c:(Draw(c.player_id,source_id=c.source_id),),GET:lambda c:(AddToHand(c.player_id,MINION,c.source_id),),
        SET:lambda c:(SetSecret(1,VEIN),),BOUNCE:lambda c:(ReturnToHand(c.target_id),),
        AUTO:lambda c:(CastSpell(c.player_id,BOOK,c.source_id),),
        OLD_COPY:lambda c:(CopyCommittedHandCard(1,c.player_id,c.source_id),)}
    for cid,body in scripts.items():
        extra={'targeting':TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))} if cid==BOUNCE else {}
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata(tribes=()),**extra))
    def fail(c):raise ResolutionError('K631 deliberate rollback after sampling')
    r.register_behavior(FAIL,fail)
    def watch(c):
        e=c.event;source=c.state.entities.get(e.source_id);target=c.state.entities.get(e.target_id)
        if mode in ('set','consume','insert'):
            if source is None or r.card(source.card_id).secret is None:return ()
            if mode=='consume':return (RemoveSecret(source.id),) if r.card(source.card_id).secret.key==SECRETS[0] else ()
            if mode=='insert':return (AddToDeck(1,SECRETS[-1],source_id=c.source_id),)
        elif mode=='reveal':
            if source is None or source.card_id!=VEIN:return ()
        elif mode=='created':
            if source is None or source.card_id!=VEIN or target is None or target.controller!=1:return ()
        else:return ()
        return (RequestChoice(1,(ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(
            RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WAIT,watch)
    event='secret_set' if mode in ('set','consume','insert') else 'secret_revealed' if mode=='reveal' else 'card_created'
    r.register_card(CardDefinition(WAIT,WAIT,CardType.MINION,cost=0,health=100,metadata=metadata(tribes=()),
        triggers=(TriggerSpec(event,WAIT),) if mode!='normal' else ()))
    r.validate();r.freeze();return r


class SecretOriginalSourceTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'
    def game(self,hand,*,deck=(),other_hand=(),other_deck=(FILL,)*10,secrets=(),mode='normal'):
        self.mode=mode
        setup=tuple(P+'setup.'+cid for cid in secrets)
        g=Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=(*setup,*hand),deck=deck,
            board=(WAIT,) if mode!='normal' else (),mana=10,max_mana=10),
            PlayerSetup('warrior.hero',hand=other_hand,deck=other_deck,mana=10,max_mana=10)),seed=631),registry(mode))
        for cid in setup:self.play(g,cid)
        return g
    def active(self,g):return [g.state.entities[i].card_id for i in g.state.players[1].secrets]
    def keys(self,g):return [g.registry.card(cid).secret.key for cid in self.active(g)]
    def opponent(self,g):g.apply(EndTurn(1))
    def copied(self,g,cid):return [g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id==cid]
    def book_rng(self,g):return [e for e in g.events if e.kind=='random_choice' and dict(e.data).get('producer')=='deck_unique_secrets']
    def waits(self,g):
        while g.state.pending_choice is not None:
            g=self.portable(g);saved=g.snapshot()
            with self.assertRaises(ResolutionError):self.choose(g,'fail')
            self.assertEqual(g.snapshot(),saved);self.choose(g)
        return g

    def test_two_complete_original_rows_four_primary_faces_and_native_secret_flag(self):
        d=native.load_batch();rows={x['record']['id']:x['record'] for x in d['dependencies']}
        for o in d['official_observations']:batch.check_face(rows[o['card_id']],o['face'],o['locale'])
        self.assertEqual((rows[BOOK]['cost'],rows[VEIN]['tags']['SECRET']),(8,1));self.assertFalse(d['formal_pool_complete'])

    def test_book_moves_original_entities_once_per_shared_secret_key(self):
        g=self.game((BOOK,),deck=(SECRETS[0],MINION,ALIAS,SECRETS[1]));original=set(g.state.players[1].deck)
        source=self.play(g,BOOK);self.assertEqual(set(self.keys(g)),set(SECRETS[:2]))
        self.assertTrue(set(g.state.players[1].secrets)<=original);self.assertEqual(len(g.state.players[1].deck),2)
        self.assertEqual(g.state.players[1].mana,2);self.assertEqual(len(g.state.cast_history),1)
        self.assertEqual(g.state.cast_history[0].source_id,source);self.portable(g)

    def test_book_first_random_domain_preserves_every_eligible_physical_duplicate(self):
        g=self.game((BOOK,),deck=(SECRETS[0],SECRETS[0],ALIAS,SECRETS[1]));ids=tuple(g.state.players[1].deck);self.play(g,BOOK)
        event=self.book_rng(g)[0];self.assertEqual(tuple(dict(event.data)['_deck_candidates']),ids)
        self.assertEqual(len(self.keys(g)),2);self.assertEqual(len(g.state.players[1].deck),2)

    def test_book_existing_alias_key_stays_in_deck(self):
        g=self.game((BOOK,),deck=(ALIAS,SECRETS[1]),secrets=(SECRETS[0],));original=g.state.players[1].deck[0];self.play(g,BOOK)
        self.assertEqual(set(self.keys(g)),set(SECRETS[:2]));self.assertIn(original,g.state.players[1].deck)

    def test_book_respects_shared_maximum_and_does_not_remove_surplus_cards(self):
        g=self.game((BOOK,),deck=SECRETS[:6],secrets=(SECRETS[0],SECRETS[1]));self.play(g,BOOK)
        self.assertEqual(len(g.state.players[1].secrets),5);self.assertEqual(len(g.state.players[1].deck),3);self.portable(g)

    def test_book_full_area_empty_domain_and_single_candidate_do_not_sample_rng(self):
        for deck,secrets in ((SECRETS[:2],SECRETS[2:7]),((MINION,),()),((SECRETS[0],),())):
            g=self.game((BOOK,),deck=deck,secrets=secrets);rng=g.snapshot()['rng_state'];self.play(g,BOOK)
            self.assertEqual(g.snapshot()['rng_state'],rng);self.assertFalse(self.book_rng(g))

    def test_book_not_a_secret_cast_or_a_draw_for_each_installed_card(self):
        g=self.game((BOOK,),deck=SECRETS[:3]);self.play(g,BOOK)
        self.assertEqual(len(g.state.cast_history),1);self.assertFalse(g.state.draw_history)

    def test_book_keeps_used_key_even_if_first_installed_secret_is_removed(self):
        g=self.game((BOOK,),deck=(SECRETS[0],ALIAS,SECRETS[1]),mode='consume');self.play(g,BOOK)
        sets=[e for e in g.events if e.kind=='secret_set' and g.registry.card(g.state.entities[e.source_id].card_id).secret.key==SECRETS[0]]
        self.assertEqual(len(sets),1);self.assertEqual(self.keys(g),[SECRETS[1]]);self.assertEqual(len(g.state.players[1].deck),1);self.portable(g)

    def test_book_does_not_admit_reaction_inserted_new_deck_cards(self):
        g=self.game((BOOK,),deck=SECRETS[:2],mode='insert');self.play(g,BOOK)
        self.assertEqual(set(self.keys(g)),set(SECRETS[:2]));self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],[SECRETS[-1]]*2)

    def test_book_installation_wait_preserves_full_original_plan_and_rng_rollback(self):
        g=self.game((BOOK,),deck=SECRETS[:3],mode='set');self.play(g,BOOK)
        self.assertIsNotNone(g.state.pending_choice);g=self.waits(g);self.assertEqual(set(self.keys(g)),set(SECRETS[:3]));self.portable(g)

    def test_book_private_deck_candidate_data_and_plan_never_enter_player_views(self):
        g=self.game((BOOK,),deck=SECRETS[:3]);self.play(g,BOOK)
        for player in (1,2):
            view=json.dumps(g.for_player(player).observe())
            for key in ('_deck_candidates','_deck_selected','used_keys','resolution_frame','rng_state'):self.assertNotIn('"'+key+'"',view)

    def test_book_public_request_rejects_duplicate_refs_wrong_zones_and_mutable_keys(self):
        g=self.game((BOOK,),deck=SECRETS[:1]);ref=CardReference.capture(g.state.entities[g.state.players[1].deck[0]])
        for args in ((1,(ref,ref),()),(1,(replace(ref,zone=Zone.HAND),),()),(1,(ref,),[]),(1,None,('x',)),(True,None,())):
            with self.assertRaises(ValueError):InstallDeckSecrets(*args)

    def test_book_completed_original_cast_cannot_be_reused_as_an_active_plan(self):
        g=self.game((BOOK,),deck=SECRETS[:1]);self.play(g,BOOK)
        with self.assertRaises(ValueError):InstallDeckSecrets(1).validate_in_state(g.state,g.registry)

    def test_book_real_automatic_cast_keeps_physical_originals_without_payment(self):
        g=self.game((AUTO,),deck=SECRETS[:2]);original=set(g.state.players[1].deck);self.play(g,AUTO)
        self.assertEqual(set(g.state.players[1].secrets),original);self.assertEqual(g.state.players[1].mana,10);self.portable(g)

    def test_vein_copies_current_turn_draw_before_minion_battlecry(self):
        g=self.game((VEIN,),other_deck=(BC,));self.play(g,VEIN);self.opponent(g);source=self.play(g,BC,player=2)
        copies=self.copied(g,BC);self.assertEqual(len(copies),1);self.assertNotEqual(copies[0].id,source)
        self.assertEqual(copies[0].cost,0);self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,1);self.portable(g)

    def test_vein_supports_actual_spell_weapon_hero_and_location_payments(self):
        for cid in (SPELL,WEAPON,HERO,LOCATION):
            g=self.game((VEIN,),other_deck=(cid,));self.play(g,VEIN);self.opponent(g);source=self.play(g,cid,player=2)
            copies=self.copied(g,cid);self.assertEqual(len(copies),1);self.assertEqual(copies[0].cost,0)
            self.assertNotEqual(copies[0].id,source);self.portable(g)

    def test_vein_does_not_trigger_for_an_initial_old_hand_card(self):
        g=self.game((VEIN,),other_hand=(MINION,));self.play(g,VEIN);self.opponent(g);self.play(g,MINION,player=2)
        self.assertFalse(self.copied(g,MINION));self.assertIn(VEIN,self.active(g))

    def test_vein_generated_card_acquired_and_played_this_turn_qualifies(self):
        g=self.game((VEIN,),other_hand=(GET,));self.play(g,VEIN);self.opponent(g);self.play(g,GET,player=2);self.play(g,MINION,player=2)
        self.assertEqual(self.copied(g,MINION)[0].cost,0);self.portable(g)

    def test_vein_uses_new_hand_entry_of_same_physical_bounced_card(self):
        g=self.game((VEIN,),other_hand=(MINION,BOUNCE));self.play(g,VEIN);self.opponent(g);source=self.play(g,MINION,player=2)
        self.assertFalse(self.copied(g,MINION));self.play(g,BOUNCE,source,player=2);again=self.play(g,MINION,player=2)
        self.assertEqual(again,source);self.assertEqual(self.copied(g,MINION)[0].cost,0);self.portable(g)

    def test_vein_previous_opponent_turn_entry_does_not_qualify_later(self):
        g=self.game((VEIN,),other_deck=(MINION,FILL));self.play(g,VEIN);self.opponent(g);g.apply(EndTurn(2));self.opponent(g)
        self.play(g,MINION,player=2);self.assertFalse(self.copied(g,MINION));self.assertIn(VEIN,self.active(g))

    def test_vein_reveal_and_copy_creation_waits_keep_original_acceptance_proof(self):
        for mode in ('reveal','created'):
            g=self.game((VEIN,),other_deck=(SPELL,),mode=mode);self.play(g,VEIN);self.opponent(g);self.play(g,SPELL,player=2)
            self.assertIsNotNone(g.state.pending_choice);g=self.waits(g);self.assertEqual(self.copied(g,SPELL)[0].cost,0);self.portable(g)

    def test_vein_full_hand_still_consumes_secret_and_uses_copy_burn(self):
        g=self.game((VEIN,)+(FILL,)*9,other_deck=(MINION,));self.play(g,VEIN);self.opponent(g);self.play(g,MINION,player=2)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertFalse(self.active(g))

    def test_vein_preserves_grown_native_ignite_material_across_two_casters(self):
        g=self.game((),other_hand=(IGNITE,DRAW,SET),other_deck=());self.opponent(g)
        self.play(g,IGNITE,g.state.players[1].hero_id,player=2);self.play(g,DRAW,player=2);self.play(g,SET,player=2)
        self.play(g,IGNITE,g.state.players[1].hero_id,player=2);copy=self.copied(g,IGNITE)[0]
        self.assertEqual((public_value(copy),copy.cost),(3,0));g.apply(EndTurn(2))
        self.play(g,IGNITE,g.state.players[2].hero_id)
        own=[g.state.entities[i] for i in g.state.players[1].deck if g.state.entities[i].card_id==IGNITE]
        self.assertEqual(public_value(own[0]),4);self.portable(g)

    def test_old_completed_play_cannot_be_copied_without_its_live_original_proof(self):
        g=self.game((OLD_COPY,),other_hand=(MINION,));self.opponent(g);self.play(g,MINION,player=2);g.apply(EndTurn(2));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,OLD_COPY)
        self.assertEqual(g.snapshot(),saved)

    def test_committed_copy_request_rejects_boolean_or_invalid_identity_fields(self):
        for args in ((True,1,1),(1,True,1),(1,1,True),(0,1,1),(1,3,1)):
            with self.assertRaises(ValueError):CopyCommittedHandCard(*args)

    def test_full_host_actual_book_installs_originals_and_vein_copies_real_drawn_minion(self):
        fmt=build_cn37_local_pool_format();r=fmt.registry
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(BOOK,),deck=(VEIN,'DEEP_000'),mana=10,max_mana=10),
            PlayerSetup('HERO_08')),generation_context=fmt.context,seed=631),r)
        original=set(g.state.players[1].deck);self.play(g,BOOK);self.assertEqual(set(g.state.players[1].secrets),original)
        body=next(cid for cid,c in r.cards.items() if c.kind==CardType.MINION and c.cost<=5 and c.health>=3 and
            not c.keywords and not c.battlecry and not c.deathrattle and not c.triggers and not c.interactable and not c.dormant_turns)
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(VEIN,),deck=(body,)*3,mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=(body,)*3,mana=10,max_mana=10)),generation_context=fmt.context,seed=631),r)
        self.play(g,VEIN);self.opponent(g);self.play(g,body,player=2);self.assertEqual(self.copied(g,body)[0].cost,0)


if __name__=='__main__':unittest.main()
