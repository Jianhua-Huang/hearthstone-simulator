"""Original shared payment endpoints, independent of later mana gains/refunds."""
KEY='_mana_available'


def payment_payload(before,after,amount):
    if any(type(x)is not int or x<0 for x in (before,after,amount)) or before-after!=amount:
        raise ValueError('Mana expenditure lost its original exact available balance')
    return {KEY:(before,after)}


def payment_available(event):
    if event is None or event.kind!='mana_spent':return None
    data=dict(event.data);value=data.get(KEY)
    if type(value)is not tuple or len(value)!=2 or event.player_id not in (1,2):
        raise ValueError('Mana payment event requires its original available endpoints')
    payment_payload(*value,event.amount)
    return value


def validate_payment_event(state,event,*,bind_hand=True):
    value=payment_available(event)
    if value is None or not bind_hand:return
    from .model import PaymentType
    plays=[p for p in state.play_history if (p.source_id,p.player_id,p.action)==
        (event.source_id,event.player_id,event.action)]
    if len(plays)>1:raise ValueError('Mana event duplicated its original physical hand play')
    if plays:
        play=plays[0]
        if play.payment!=PaymentType.MANA or play.cost!=event.amount or (play.mana_before,play.mana_after)!=value:
            raise ValueError('Mana event changed its original submitted hand payment endpoints')


def exhausted(event):
    if event is None:return False
    if event.kind=='mana_spent':
        values=payment_available(event)
        return event.amount>0 and values[1]==0
    if event.kind=='mana_consumed':
        from .resources import mana_consumption_result
        row=mana_consumption_result(event)
        return row is not None and row.actual>0 and row.mana_after==0
    return False
