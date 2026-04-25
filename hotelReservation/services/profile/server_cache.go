//go:build !no_memcache

package profile

import (
	"context"
	"encoding/json"
	"sync"

	"github.com/bradfitz/gomemcache/memcache"
	"github.com/opentracing/opentracing-go"
	"github.com/rs/zerolog/log"
	"go.mongodb.org/mongo-driver/bson"

	pb "github.com/delimitrou/DeathStarBench/tree/master/hotelReservation/services/profile/proto"
)

// GetProfiles returns hotel profiles for requested IDs, using Memcached as a read-through cache.
func (s *Server) GetProfiles(ctx context.Context, req *pb.Request) (*pb.Result, error) {
	log.Trace().Msgf("In GetProfiles")

	var wg sync.WaitGroup
	var mutex sync.Mutex

	// one hotel should only have one profile
	hotelIds := make([]string, 0)
	profileMap := make(map[string]struct{})
	for _, hotelId := range req.HotelIds {
		hotelIds = append(hotelIds, hotelId)
		profileMap[hotelId] = struct{}{}
	}

	memSpan, _ := opentracing.StartSpanFromContext(ctx, "memcached_get_profile")
	memSpan.SetTag("span.kind", "client")
	resMap, err := s.MemcClient.GetMulti(hotelIds)
	memSpan.Finish()

	res := new(pb.Result)
	hotels := make([]*pb.Hotel, 0)

	if err != nil && err != memcache.ErrCacheMiss {
		log.Panic().Msgf("Tried to get hotelIds [%v], but got memmcached error = %s", hotelIds, err)
	} else {
		for hotelId, item := range resMap {
			profileStr := string(item.Value)
			log.Trace().Msgf("memc hit with %v", profileStr)

			hotelProf := new(pb.Hotel)
			json.Unmarshal(item.Value, hotelProf)
			hotels = append(hotels, hotelProf)
			delete(profileMap, hotelId)
		}

		wg.Add(len(profileMap))
		for hotelId := range profileMap {
			go func(hotelId string) {
				var hotelProf *pb.Hotel

				collection := s.MongoClient.Database("profile-db").Collection("hotels")

				mongoSpan, _ := opentracing.StartSpanFromContext(ctx, "mongo_profile")
				mongoSpan.SetTag("span.kind", "client")
				err := collection.FindOne(context.TODO(), bson.D{{"id", hotelId}}).Decode(&hotelProf)
				mongoSpan.Finish()

				if err != nil {
					log.Error().Msgf("Failed get hotels data: %v", err)
				}

				mutex.Lock()
				hotels = append(hotels, hotelProf)
				mutex.Unlock()

				profJson, err := json.Marshal(hotelProf)
				if err != nil {
					log.Error().Msgf("Failed to marshal hotel [id: %v] with err: %v", hotelProf.Id, err)
				}
				memcStr := string(profJson)

				// write to memcached
				go s.MemcClient.Set(&memcache.Item{Key: hotelId, Value: []byte(memcStr)})
				defer wg.Done()
			}(hotelId)
		}
	}
	wg.Wait()

	res.Hotels = hotels
	log.Trace().Msgf("In GetProfiles after getting resp")
	return res, nil
}
