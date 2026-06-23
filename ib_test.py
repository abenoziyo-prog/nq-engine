from ib_async import IB, Future

ib = IB()
ib.connect('127.0.0.1', 4002, clientId=1)
print("Connected:", ib.isConnected())

ib.reqMarketDataType(3)   # delayed

mnq = Future(symbol='MNQ', lastTradeDateOrContractMonth='20260918',
             exchange='CME', currency='USD')
contracts = ib.qualifyContracts(mnq)

ticker = ib.reqMktData(contracts[0])

# poll up to 10s for data to arrive
for i in range(10):
    ib.sleep(1)
    if ticker.last == ticker.last or ticker.close == ticker.close:  # not nan
        if not (ticker.last != ticker.last and ticker.close != ticker.close
                and ticker.bid != ticker.bid and ticker.ask != ticker.ask):
            break

print(f"marketDataType: {ticker.marketDataType}")
print(f"MNQ  bid={ticker.bid}  ask={ticker.ask}  last={ticker.last}  close={ticker.close}")

ib.disconnect()
