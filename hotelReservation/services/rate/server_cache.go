//go:build !no_memcache

package rate

import (
	"context"
	"encoding/json"
	"sort"
	"strings"
	"sync"

	"github.com/bradfitz/gomemcache/memcache"
	pb "github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/services/rate/proto"
	"github.com/opentracing/opentracing-go"
	"github.com/rs/zerolog/log"
	"go.mongodb.org/mongo-driver/bson"
)

// GetRates gets rates for hotels for specific date range.
func (s *Server) GetRates(ctx context.Context, req *pb.Request) (*pb.Result, error) {
	res := new(pb.Result)

	ratePlans := make(RatePlans, 0)

	hotelIds := []string{}
	rateMap := make(map[string]struct{})
	for _, hotelID := range req.HotelIds {
		hotelIds = append(hotelIds, hotelID)
		rateMap[hotelID] = struct{}{}
	}
	// first check memcached(get-multi)
	memSpan, _ := opentracing.StartSpanFromContext(ctx, "memcached_get_multi_rate")
	memSpan.SetTag("span.kind", "client")

	resMap, err := s.MemcClient.GetMulti(hotelIds)
	memSpan.Finish()

	var wg sync.WaitGroup
	var mutex sync.Mutex
	if err != nil && err != memcache.ErrCacheMiss {
		log.Panic().Msgf("Memmcached error while trying to get hotel [id: %v]= %s", hotelIds, err)
	} else {
		for hotelId, item := range resMap {
			rateStrs := strings.Split(string(item.Value), "\n")
			log.Trace().Msgf("memc hit, hotelId = %s,rate strings: %v", hotelId, rateStrs)

			for _, rateStr := range rateStrs {
				if len(rateStr) != 0 {
					rateP := new(pb.RatePlan)
					json.Unmarshal([]byte(rateStr), rateP)
					ratePlans = append(ratePlans, rateP)
				}
			}

			delete(rateMap, hotelId)
		}

		wg.Add(len(rateMap))
		for hotelId := range rateMap {
			go func(id string) {
				defer wg.Done()

				log.Trace().Msgf("memc miss, hotelId = %s", id)
				log.Trace().Msg("memcached miss, set up mongo connection")

				mongoSpan, _ := opentracing.StartSpanFromContext(ctx, "mongo_rate")
				mongoSpan.SetTag("span.kind", "client")

				// memcached miss, set up mongo connection
				collection := s.MongoClient.Database("rate-db").Collection("inventory")
				curr, err := collection.Find(context.TODO(), bson.D{})
				if err != nil {
					log.Error().Msgf("Failed get rate data: %v", err)
				}

				tmpRatePlans := make(RatePlans, 0)
				if curr != nil {
					err = curr.All(context.TODO(), &tmpRatePlans)
				}
				if err != nil {
					log.Error().Msgf("Failed get rate data: %v", err)
				}

				mongoSpan.Finish()

				memcStr := ""
				if err != nil {
					log.Panic().Msgf("Tried to find hotelId [%v], but got error %v", id, err)
				} else {
					for _, r := range tmpRatePlans {
						mutex.Lock()
						ratePlans = append(ratePlans, r)
						mutex.Unlock()
						rateJSON, err := json.Marshal(r)
						if err != nil {
							log.Error().Msgf("Failed to marshal plan [Code: %v] with error: %s", r.Code, err)
						}
						memcStr = memcStr + string(rateJSON) + "\n"
					}
				}
				go s.MemcClient.Set(&memcache.Item{Key: id, Value: []byte(memcStr)})
			}(hotelId)
		}
	}
	wg.Wait()

	sort.Sort(ratePlans)
	res.RatePlans = ratePlans

	return res, nil
}
